import asyncio, csv, io
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import BackgroundTasks, Body, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .config import get_settings
from .database import Base, SessionLocal, engine, get_db
from .models import Account, Activity, FollowUpTask, Prospect, ProspectPreference, ProspectResearchState, ResearchJob, ScoringRule
from .outreach import OutreachConfigurationError, OutreachProviderError, generate_outreach
from .research import normalize_domain, refresh_account, refresh_prospect
from .schemas import AccountOut, ActivityOut, FollowUpCreate, FollowUpOut, FollowUpUpdate, IcpUpdate, ImportResult, OutreachOut, RefreshResult, ResearchJobOut, ResearchStatusOut, ScoringRuleOut, ScoringRuleUpdate
from .scoring import DEFAULT_RULES, calculate

ROOT=Path(__file__).resolve().parent.parent
# An AsyncIOScheduler binds to the running event loop.  Create it at startup,
# rather than import time, so TestClient and reloads can use fresh loops.
scheduler: AsyncIOScheduler | None = None
research_queue: asyncio.Queue[int] | None = None
research_workers: list[asyncio.Task] = []
ACTIVE_JOB_STATUSES=("QUEUED","RUNNING")

ACCOUNT_LOAD_OPTIONS=(
    selectinload(Account.prospects).selectinload(Prospect.research_state).selectinload(ProspectResearchState.signals),
    selectinload(Account.prospects).selectinload(Prospect.follow_ups),
    selectinload(Account.prospects).selectinload(Prospect.contact_preference),
    selectinload(Account.signals),
)

async def enqueue_account_jobs(account_ids:list[int], trigger:str) -> list[int]:
    db=SessionLocal()
    try:
        job_ids=[]
        for account_id in account_ids:
            active=db.scalar(select(ResearchJob).where(ResearchJob.account_id==account_id,ResearchJob.prospect_id.is_(None),ResearchJob.status.in_(ACTIVE_JOB_STATUSES)).order_by(ResearchJob.created_at.desc()))
            if active: continue
            job=ResearchJob(scope="ACCOUNT",trigger=trigger,account_id=account_id,status="QUEUED")
            db.add(job); db.flush(); job_ids.append(job.id)
            db.add(Activity(account_id=account_id,activity_type="RESEARCH_QUEUED",detail=f"Company research queued by {trigger.lower()}."))
        db.commit()
    finally: db.close()
    if research_queue:
        for job_id in job_ids: await research_queue.put(job_id)
    return job_ids

async def refresh_all_job():
    db=SessionLocal()
    try: account_ids=list(db.scalars(select(Account.id)))
    finally: db.close()
    await enqueue_account_jobs(account_ids,"SCHEDULE")

async def process_research_job(job_id:int):
    db=SessionLocal()
    try:
        job=db.get(ResearchJob,job_id)
        if not job or job.status!="QUEUED": return
        job.status="RUNNING"; job.started_at=datetime.now(timezone.utc); db.add(Activity(account_id=job.account_id,activity_type="RESEARCH_STARTED",detail=f"{job.scope.title()} research started ({job.trigger.lower()}).")); db.commit()
        if job.scope=="PROSPECT" and job.prospect_id:
            count=await refresh_prospect(db,job.prospect_id,get_settings().company_freshness_minutes)
        else:
            count,_,_=await refresh_account(db,job.account_id)
        job=db.get(ResearchJob,job_id); job.status="COMPLETED"; job.signals_found=count; job.completed_at=datetime.now(timezone.utc); job.error_message=None
        db.add(Activity(account_id=job.account_id,activity_type="RESEARCH_JOB_COMPLETED",detail=f"{job.scope.title()} research completed with {count} signals.")); db.commit()
    except Exception as exc:
        db.rollback(); job=db.get(ResearchJob,job_id)
        if job:
            job.status="FAILED"; job.error_message=str(exc)[:500]; job.completed_at=datetime.now(timezone.utc)
            db.add(Activity(account_id=job.account_id,activity_type="RESEARCH_JOB_FAILED",detail=f"{job.scope.title()} research failed.")); db.commit()
    finally: db.close()

async def research_worker_loop(queue:asyncio.Queue):
    # Hold a local reference: the global is cleared on shutdown, and a cancelled
    # worker still runs its finally block afterwards.
    while True:
        job_id=await queue.get()
        try: await process_research_job(job_id)
        except asyncio.CancelledError: raise
        except Exception: pass
        finally: queue.task_done()

def seed_scoring_rules(db:Session):
    existing=set(db.scalars(select(ScoringRule.key)))
    for key,label,category,value,match_text,description in DEFAULT_RULES:
        if key not in existing: db.add(ScoringRule(key=key,label=label,category=category,value=value,match_text=match_text,description=description))
    db.commit()

def rescore_all_accounts(db:Session) -> int:
    rules=list(db.scalars(select(ScoringRule)))
    items=list(db.scalars(select(Account).options(selectinload(Account.prospects),selectinload(Account.signals))).unique())
    for item in items:
        item.previous_score=item.nba_score
        result=calculate(item,rules); item.nba_score=result.score; item.recommended_action=result.action
    return len(items)

def attach_score_breakdowns(items:list[Account],db:Session):
    rules=list(db.scalars(select(ScoringRule)))
    for item in items:
        result=calculate(item,rules)
        item.score_breakdown={"icp":result.icp,"signals":result.signals,"engagement":result.engagement,"timing":result.timing,"persona":result.persona}
    return items

@asynccontextmanager
async def lifespan(_:FastAPI):
    global scheduler, research_queue, research_workers
    Base.metadata.create_all(engine)
    db=SessionLocal()
    try:
        seed_scoring_rules(db); rescore_all_accounts(db); db.commit()
        for job in db.scalars(select(ResearchJob).where(ResearchJob.status.in_(ACTIVE_JOB_STATUSES))):
            job.status="INTERRUPTED"; job.completed_at=datetime.now(timezone.utc); job.error_message="Application restarted before job completion."
        db.commit(); account_ids=list(db.scalars(select(Account.id)))
    finally: db.close()
    research_queue=asyncio.Queue(); research_workers=[asyncio.create_task(research_worker_loop(research_queue)) for _ in range(max(1,get_settings().research_worker_count))]
    scheduler=AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(refresh_all_job,"interval",minutes=get_settings().research_interval_minutes,id="company-refresh",replace_existing=True,max_instances=1,coalesce=True,misfire_grace_time=300)
    scheduler.start()
    if get_settings().startup_refresh_enabled: await enqueue_account_jobs(account_ids,"STARTUP")
    yield
    if scheduler.running: scheduler.shutdown(wait=False)
    scheduler=None
    for worker in research_workers: worker.cancel()
    await asyncio.gather(*research_workers,return_exceptions=True)
    research_workers=[]; research_queue=None

app=FastAPI(title="SDR Next API",version="1.0.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:8000","http://127.0.0.1:8000"],allow_methods=["*"],allow_headers=["*"])
app.mount("/static",StaticFiles(directory=ROOT/"static"),name="static")

def load_account(db:Session,account_id:int):
    return db.scalar(select(Account).where(Account.id==account_id).options(*ACCOUNT_LOAD_OPTIONS))

@app.get("/",include_in_schema=False)
def index(): return FileResponse(ROOT/"static"/"index.html")

@app.get("/api/health")
def health(): return {"status":"ok","scheduler_running":bool(scheduler and scheduler.running),"research_worker_running":any(not worker.done() for worker in research_workers)}

@app.get("/api/accounts",response_model=list[AccountOut])
def accounts(db:Session=Depends(get_db)):
    return attach_score_breakdowns(list(db.scalars(select(Account).options(*ACCOUNT_LOAD_OPTIONS).order_by(Account.nba_score.desc())).unique()),db)

@app.get("/api/accounts/{account_id}",response_model=AccountOut)
def account(account_id:int,db:Session=Depends(get_db)):
    item=load_account(db,account_id)
    if not item: raise HTTPException(404,"Account not found")
    return attach_score_breakdowns([item],db)[0]

@app.get("/api/activity",response_model=list[ActivityOut])
def activity(limit:int=100,db:Session=Depends(get_db)):
    return list(db.scalars(select(Activity).order_by(Activity.created_at.desc()).limit(min(max(limit,1),500))))

@app.get("/api/scoring-rules",response_model=list[ScoringRuleOut])
def scoring_rules(db:Session=Depends(get_db)):
    return list(db.scalars(select(ScoringRule).order_by(ScoringRule.category,ScoringRule.label)))

@app.put("/api/scoring-rules",response_model=list[ScoringRuleOut])
def update_scoring_rules(updates:list[ScoringRuleUpdate]=Body(...),db:Session=Depends(get_db)):
    if not updates: raise HTTPException(400,"Provide at least one scoring rule")
    keys={update.key for update in updates}
    rows={row.key:row for row in db.scalars(select(ScoringRule).where(ScoringRule.key.in_(keys)))}
    if keys != set(rows): raise HTTPException(404,"One or more scoring rules do not exist")
    for update in updates:
        if not 0 <= update.value <= 100: raise HTTPException(400,"Rule values must be between 0 and 100")
        rows[update.key].value=update.value
    count=rescore_all_accounts(db)
    db.add(Activity(activity_type="SCORING_RULES_UPDATED",detail=f"Updated {len(updates)} scoring rules and recalculated {count} accounts."))
    db.commit()
    return list(db.scalars(select(ScoringRule).order_by(ScoringRule.category,ScoringRule.label)))

@app.patch("/api/accounts/{account_id}/icp",response_model=AccountOut)
def update_icp(account_id:int,payload:IcpUpdate,db:Session=Depends(get_db)):
    item=load_account(db,account_id)
    if not item: raise HTTPException(404,"Account not found")
    if not 0 <= payload.icp_score <= 100: raise HTTPException(400,"ICP score must be between 0 and 100")
    item.previous_score=item.nba_score; item.icp_score=payload.icp_score
    result=calculate(item,list(db.scalars(select(ScoringRule)))); item.nba_score=result.score; item.recommended_action=result.action
    db.add(Activity(account_id=item.id,activity_type="ICP_UPDATED",detail=f"ICP score set to {payload.icp_score}; NBA score is now {item.nba_score}."))
    db.commit(); return attach_score_breakdowns([load_account(db,account_id)],db)[0]

@app.post("/api/import",response_model=ImportResult)
async def import_csv(background:BackgroundTasks,file:UploadFile=File(...),db:Session=Depends(get_db)):
    if not (file.filename or "").lower().endswith(".csv"): raise HTTPException(400,"Upload a CSV file")
    raw=await file.read()
    if len(raw)>2_000_000: raise HTTPException(413,"CSV is limited to 2 MB")
    try: reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    except UnicodeDecodeError: raise HTTPException(400,"CSV must use UTF-8 encoding")
    required={"company_name","company_domain","prospect_name","prospect_title"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)): raise HTTPException(400,f"Required columns: {', '.join(sorted(required))}")
    imported=updated=0; rejected=[]; ids=[]
    for line,row in enumerate(reader,start=2):
        try:
            domain=normalize_domain(row["company_domain"])
            name=(row["company_name"] or "").strip(); prospect_name=(row["prospect_name"] or "").strip(); title=(row["prospect_title"] or "").strip()
            if not all((name,prospect_name,title)): raise ValueError("required value is empty")
            item=db.scalar(select(Account).where(Account.domain==domain))
            if item: item.name=name; updated+=1; event="ACCOUNT_UPDATED"
            else:
                item=Account(name=name,domain=domain,industry=(row.get("industry") or "").strip() or None,employee_count=int(row["employee_count"]) if (row.get("employee_count") or "").isdigit() else None,icp_score=int(row["icp_score"]) if (row.get("icp_score") or "").isdigit() else 60)
                db.add(item); db.flush(); imported+=1; event="ACCOUNT_IMPORTED"
            existing=db.scalar(select(Prospect).where(Prospect.account_id==item.id,Prospect.name==prospect_name))
            if not existing: db.add(Prospect(account_id=item.id,name=prospect_name,title=title,email=(row.get("email") or "").strip() or None,phone=(row.get("phone") or "").strip() or None))
            db.add(Activity(account_id=item.id,activity_type=event,detail=f"{name} was {'imported' if event == 'ACCOUNT_IMPORTED' else 'updated'} from CSV."))
            ids.append(item.id)
        except Exception as exc: rejected.append(f"Line {line}: {exc}")
    db.commit(); await enqueue_account_jobs(list(dict.fromkeys(ids)),"IMPORT")
    return ImportResult(imported=imported,updated=updated,rejected=rejected,research_started=bool(ids))

@app.post("/api/accounts/{account_id}/refresh",response_model=RefreshResult)
async def refresh(account_id:int,db:Session=Depends(get_db)):
    try: count,score,action=await refresh_account(db,account_id)
    except ValueError as exc: raise HTTPException(404,str(exc))
    except Exception as exc: raise HTTPException(502,f"Research failed: {exc}")
    return RefreshResult(account_id=account_id,status="READY",signals_found=count,score=score,action=action)

@app.post("/api/prospects/{prospect_id}/refresh",response_model=ResearchJobOut,status_code=202)
async def refresh_prospect_background(prospect_id:int,db:Session=Depends(get_db)):
    prospect=db.get(Prospect,prospect_id)
    if not prospect: raise HTTPException(404,"prospect not found")
    existing=db.scalar(select(ResearchJob).where(ResearchJob.prospect_id==prospect_id,ResearchJob.status.in_(ACTIVE_JOB_STATUSES)).order_by(ResearchJob.created_at.desc()))
    if existing: return existing
    recent=db.scalar(select(ResearchJob).where(ResearchJob.prospect_id==prospect_id,ResearchJob.status=="COMPLETED",ResearchJob.completed_at>=datetime.now(timezone.utc)-timedelta(minutes=get_settings().person_refresh_cooldown_minutes)).order_by(ResearchJob.completed_at.desc()))
    if recent: return recent
    job=ResearchJob(scope="PROSPECT",trigger="MANUAL",status="QUEUED",account_id=prospect.account_id,prospect_id=prospect.id)
    db.add(job); db.flush(); db.add(Activity(account_id=prospect.account_id,activity_type="PERSON_RESEARCH_QUEUED",detail=f"Public person research queued for {prospect.name}.")); db.commit(); db.refresh(job)
    if research_queue: await research_queue.put(job.id)
    return job

@app.post("/api/prospects/{prospect_id}/outreach",response_model=OutreachOut)
async def generate_prospect_outreach(prospect_id:int,db:Session=Depends(get_db)):
    prospect=db.get(Prospect,prospect_id)
    if not prospect: raise HTTPException(404,"prospect not found")
    account=load_account(db,prospect.account_id)
    prospect=next((item for item in account.prospects if item.id==prospect_id),None) if account else None
    if not account or not prospect: raise HTTPException(404,"prospect not found")
    try:
        draft=await generate_outreach(account,prospect)
    except OutreachConfigurationError as exc:
        raise HTTPException(503,str(exc))
    except OutreachProviderError:
        raise HTTPException(502,"Gemini could not generate the outreach draft. Try again shortly.")
    db.add(Activity(account_id=account.id,activity_type="AI_OUTREACH_GENERATED",detail=f"Gemini generated a source-grounded outreach draft for {prospect.name}.")); db.commit()
    return OutreachOut(prospect_id=prospect.id,model=get_settings().gemini_model,**draft.__dict__)

def utc_datetime(value:datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

@app.get("/api/follow-ups",response_model=list[FollowUpOut])
def follow_ups(status:str="OPEN",db:Session=Depends(get_db)):
    if status not in {"OPEN","DONE","ALL"}: raise HTTPException(400,"status must be OPEN, DONE, or ALL")
    query=select(FollowUpTask).order_by(FollowUpTask.due_at)
    if status!="ALL": query=query.where(FollowUpTask.status==status)
    return list(db.scalars(query))

@app.post("/api/prospects/{prospect_id}/follow-ups",response_model=FollowUpOut,status_code=201)
def create_follow_up(prospect_id:int,payload:FollowUpCreate,db:Session=Depends(get_db)):
    prospect=db.get(Prospect,prospect_id)
    if not prospect: raise HTTPException(404,"prospect not found")
    if prospect.do_not_contact: raise HTTPException(409,"This prospect is marked do not contact")
    task=FollowUpTask(prospect_id=prospect.id,owner=payload.owner.strip(),next_step=payload.next_step.strip(),due_at=utc_datetime(payload.due_at),status="OPEN")
    db.add(task); db.flush(); db.add(Activity(account_id=prospect.account_id,activity_type="FOLLOW_UP_CREATED",detail=f"Follow-up for {prospect.name}: {task.next_step}")); db.commit(); db.refresh(task)
    return task

@app.patch("/api/follow-ups/{task_id}",response_model=FollowUpOut)
def update_follow_up(task_id:int,payload:FollowUpUpdate,db:Session=Depends(get_db)):
    task=db.get(FollowUpTask,task_id)
    if not task: raise HTTPException(404,"follow-up not found")
    if all(value is None for value in (payload.status,payload.due_at,payload.owner,payload.next_step)): raise HTTPException(400,"Provide at least one follow-up change")
    if payload.status is not None:
        task.status=payload.status; task.completed_at=datetime.now(timezone.utc) if payload.status=="DONE" else None
    if payload.due_at is not None: task.due_at=utc_datetime(payload.due_at)
    if payload.owner is not None: task.owner=payload.owner.strip()
    if payload.next_step is not None: task.next_step=payload.next_step.strip()
    prospect=db.get(Prospect,task.prospect_id)
    event="FOLLOW_UP_COMPLETED" if payload.status=="DONE" else "FOLLOW_UP_UPDATED"
    db.add(Activity(account_id=prospect.account_id,activity_type=event,detail=f"Follow-up for {prospect.name} {'completed' if event=='FOLLOW_UP_COMPLETED' else 'updated'}.")); db.commit(); db.refresh(task)
    return task

@app.put("/api/prospects/{prospect_id}/contact-preference")
def set_contact_preference(prospect_id:int,do_not_contact:bool=Body(...,embed=True),db:Session=Depends(get_db)):
    prospect=db.get(Prospect,prospect_id)
    if not prospect: raise HTTPException(404,"prospect not found")
    preference=prospect.contact_preference
    if not preference:
        preference=ProspectPreference(prospect_id=prospect.id); db.add(preference)
    preference.do_not_contact=do_not_contact
    state="marked do not contact" if do_not_contact else "made contactable"
    db.add(Activity(account_id=prospect.account_id,activity_type="CONTACT_PREFERENCE_UPDATED",detail=f"{prospect.name} was {state}.")); db.commit()
    return {"prospect_id":prospect.id,"do_not_contact":do_not_contact}

@app.get("/api/research-jobs/{job_id}",response_model=ResearchJobOut)
def research_job(job_id:int,db:Session=Depends(get_db)):
    job=db.get(ResearchJob,job_id)
    if not job: raise HTTPException(404,"research job not found")
    return job

@app.get("/api/research-status",response_model=ResearchStatusOut)
def research_status(db:Session=Depends(get_db)):
    jobs=list(db.scalars(select(ResearchJob).order_by(ResearchJob.created_at.desc())))
    completed=next((job.completed_at for job in jobs if job.status=="COMPLETED" and job.completed_at),None)
    scheduled=scheduler.get_job("company-refresh") if scheduler else None
    return ResearchStatusOut(queued=sum(job.status=="QUEUED" for job in jobs),running=sum(job.status=="RUNNING" for job in jobs),last_completed_at=completed,next_scheduled_at=scheduled.next_run_time if scheduled else None,interval_minutes=get_settings().research_interval_minutes)

@app.post("/api/refresh-all")
async def refresh_all(db:Session=Depends(get_db)):
    ids=list(db.scalars(select(Account.id))); jobs=await enqueue_account_jobs(ids,"MANUAL")
    return {"status":"started","accounts":len(ids),"queued":len(jobs)}
