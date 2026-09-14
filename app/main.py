import csv, io
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .config import get_settings
from .database import Base, SessionLocal, engine, get_db
from .models import Account, Prospect
from .research import normalize_domain, refresh_account
from .schemas import AccountOut, ImportResult, RefreshResult

ROOT=Path(__file__).resolve().parent.parent
scheduler: AsyncIOScheduler | None = None

async def refresh_all_job():
    db=SessionLocal()
    try:
        ids=list(db.scalars(select(Account.id)))
        for account_id in ids:
            try: await refresh_account(db,account_id)
            except Exception: continue
    finally: db.close()

@asynccontextmanager
async def lifespan(_:FastAPI):
    global scheduler
    Base.metadata.create_all(engine)
    scheduler=AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(refresh_all_job,"interval",minutes=get_settings().research_interval_minutes,id="company-refresh",replace_existing=True,max_instances=1)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)
    scheduler=None

app=FastAPI(title="SDR Next API",version="1.0.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:8000","http://127.0.0.1:8000"],allow_methods=["*"],allow_headers=["*"])
app.mount("/static",StaticFiles(directory=ROOT/"static"),name="static")

def load_account(db:Session,account_id:int):
    return db.scalar(select(Account).where(Account.id==account_id).options(selectinload(Account.prospects),selectinload(Account.signals)))

async def research_ids(ids:list[int]):
    db=SessionLocal()
    try:
        for account_id in ids:
            try: await refresh_account(db,account_id)
            except Exception: continue
    finally: db.close()

@app.get("/",include_in_schema=False)
def index(): return FileResponse(ROOT/"static"/"index.html")

@app.get("/api/health")
def health(): return {"status":"ok","scheduler_running":bool(scheduler and scheduler.running)}

@app.get("/api/accounts",response_model=list[AccountOut])
def accounts(db:Session=Depends(get_db)):
    return list(db.scalars(select(Account).options(selectinload(Account.prospects),selectinload(Account.signals)).order_by(Account.nba_score.desc())).unique())

@app.get("/api/accounts/{account_id}",response_model=AccountOut)
def account(account_id:int,db:Session=Depends(get_db)):
    item=load_account(db,account_id)
    if not item: raise HTTPException(404,"Account not found")
    return item

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
            if item: item.name=name; updated+=1
            else:
                item=Account(name=name,domain=domain,industry=(row.get("industry") or "").strip() or None,employee_count=int(row["employee_count"]) if (row.get("employee_count") or "").isdigit() else None,icp_score=int(row["icp_score"]) if (row.get("icp_score") or "").isdigit() else 60)
                db.add(item); db.flush(); imported+=1
            existing=db.scalar(select(Prospect).where(Prospect.account_id==item.id,Prospect.name==prospect_name))
            if not existing: db.add(Prospect(account_id=item.id,name=prospect_name,title=title,email=(row.get("email") or "").strip() or None,phone=(row.get("phone") or "").strip() or None))
            ids.append(item.id)
        except Exception as exc: rejected.append(f"Line {line}: {exc}")
    db.commit(); background.add_task(research_ids,list(dict.fromkeys(ids)))
    return ImportResult(imported=imported,updated=updated,rejected=rejected,research_started=bool(ids))

@app.post("/api/accounts/{account_id}/refresh",response_model=RefreshResult)
async def refresh(account_id:int,db:Session=Depends(get_db)):
    try: count,score,action=await refresh_account(db,account_id)
    except ValueError as exc: raise HTTPException(404,str(exc))
    except Exception as exc: raise HTTPException(502,f"Research failed: {exc}")
    return RefreshResult(account_id=account_id,status="READY",signals_found=count,score=score,action=action)

@app.post("/api/refresh-all")
async def refresh_all(background:BackgroundTasks,db:Session=Depends(get_db)):
    ids=list(db.scalars(select(Account.id))); background.add_task(research_ids,ids)
    return {"status":"started","accounts":len(ids)}
