import os
os.environ["DATABASE_URL"]="sqlite:///./data/test_sdr_next.db"
import asyncio, time
import pytest
from fastapi.testclient import TestClient
from app.database import Base, SessionLocal, engine
from app import main
from app.models import Account, Prospect

app=main.app

@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)

def test_health_and_dashboard():
    with TestClient(app) as client:
        health=client.get("/api/health")
        assert health.status_code==200
        assert health.json()["status"]=="ok"
        page=client.get("/")
        assert page.status_code==200
        assert "Good morning, Manvi" in page.text

def test_import_rejects_wrong_columns():
    with TestClient(app) as client:
        response=client.post("/api/import",files={"file":("bad.csv",b"company,person\nA,B\n","text/csv")})
        assert response.status_code==400

def test_import_rejects_non_csv():
    with TestClient(app) as client:
        response=client.post("/api/import",files={"file":("bad.txt",b"hello","text/plain")})
        assert response.status_code==400

def test_scoring_rules_icp_and_activity_are_persisted():
    with TestClient(app) as client:
        rules=client.get("/api/scoring-rules")
        assert rules.status_code==200
        research_rule=next(rule for rule in rules.json() if rule["key"]=="action_research_score")
        updated=client.put("/api/scoring-rules",json=[{"key":"action_research_score","value":research_rule["value"]}])
        assert updated.status_code==200
        db=SessionLocal(); account=Account(name="Settings test",domain="settings-test.example",icp_score=60)
        db.add(account); db.flush(); db.add(Prospect(account_id=account.id,name="Alex",title="VP Sales")); db.commit(); account_id=account.id; db.close()
        response=client.patch(f"/api/accounts/{account_id}/icp",json={"icp_score":82})
        assert response.status_code==200
        assert response.json()["icp_score"]==82
        assert any(item["activity_type"]=="ICP_UPDATED" for item in client.get("/api/activity").json())

def test_person_refresh_is_background_and_deduplicated(monkeypatch):
    async def fake_refresh(db, prospect_id, freshness_minutes):
        await asyncio.sleep(.08)
        return 2
    monkeypatch.setattr(main,"refresh_prospect",fake_refresh)
    with TestClient(app) as client:
        db=SessionLocal(); account=Account(name="Acme",domain="acme.example"); db.add(account); db.flush(); prospect=Prospect(account_id=account.id,name="Alex Smith",title="VP Sales"); db.add(prospect); db.commit(); prospect_id=prospect.id; db.close()
        first=client.post(f"/api/prospects/{prospect_id}/refresh")
        second=client.post(f"/api/prospects/{prospect_id}/refresh")
        assert first.status_code==202 and second.status_code==202
        assert first.json()["id"]==second.json()["id"]
        deadline=time.time()+2; job=first.json()
        while time.time()<deadline:
            job=client.get(f"/api/research-jobs/{job['id']}").json()
            if job["status"] in {"COMPLETED","FAILED"}: break
            time.sleep(.03)
        assert job["status"]=="COMPLETED"
        assert job["signals_found"]==2
        third=client.post(f"/api/prospects/{prospect_id}/refresh")
        assert third.status_code==202 and third.json()["id"]==job["id"]
        status=client.get("/api/research-status").json()
        assert status["interval_minutes"]==30

def test_missing_prospect_refresh_returns_404():
    with TestClient(app) as client:
        assert client.post("/api/prospects/99999/refresh").status_code==404

def test_outreach_draft_is_source_grounded_and_audited(monkeypatch):
    async def fake_generate(account, prospect):
        from app.outreach import OutreachDraft
        assert account.name=="Acme" and prospect.name=="Alex Smith"
        return OutreachDraft(subject="A practical Acme idea",opening_line="I have a practical idea for Acme.",email_body="Alex, I wanted to share a concise idea that may help your team prioritise the next step. Would a short conversation next week be useful?",call_talk_track="Ask whether this priority is already on Alex's team roadmap.",source_urls=["https://acme.example/news"])
    monkeypatch.setattr(main,"generate_outreach",fake_generate)
    with TestClient(app) as client:
        db=SessionLocal(); account=Account(name="Acme",domain="acme.example"); db.add(account); db.flush(); prospect=Prospect(account_id=account.id,name="Alex Smith",title="VP Sales"); db.add(prospect); db.commit(); prospect_id=prospect.id; db.close()
        response=client.post(f"/api/prospects/{prospect_id}/outreach")
        assert response.status_code==200
        assert response.json()["subject"]=="A practical Acme idea"
        assert response.json()["source_urls"]==["https://acme.example/news"]
        assert any(item["activity_type"]=="AI_OUTREACH_GENERATED" for item in client.get("/api/activity").json())

def test_missing_prospect_outreach_returns_404():
    with TestClient(app) as client:
        assert client.post("/api/prospects/99999/outreach").status_code==404

def test_follow_up_workflow_and_do_not_contact_are_persisted():
    with TestClient(app) as client:
        db=SessionLocal(); account=Account(name="Acme",domain="acme.example"); db.add(account); db.flush(); prospect=Prospect(account_id=account.id,name="Alex Smith",title="VP Sales"); db.add(prospect); db.commit(); prospect_id=prospect.id; account_id=account.id; db.close()
        created=client.post(f"/api/prospects/{prospect_id}/follow-ups",json={"owner":"Manvi","next_step":"Call about the research finding","due_at":"2026-10-01T09:00:00Z"})
        assert created.status_code==201
        task_id=created.json()["id"]
        account=client.get(f"/api/accounts/{account_id}").json()
        assert account["prospects"][0]["follow_ups"][0]["id"]==task_id
        done=client.patch(f"/api/follow-ups/{task_id}",json={"status":"DONE"})
        assert done.status_code==200 and done.json()["completed_at"]
        preference=client.put(f"/api/prospects/{prospect_id}/contact-preference",json={"do_not_contact":True})
        assert preference.status_code==200 and preference.json()["do_not_contact"] is True
        blocked=client.post(f"/api/prospects/{prospect_id}/follow-ups",json={"next_step":"Try again","due_at":"2026-10-02T09:00:00Z"})
        assert blocked.status_code==409
        activity=client.get("/api/activity").json()
        assert {"FOLLOW_UP_CREATED","FOLLOW_UP_COMPLETED","CONTACT_PREFERENCE_UPDATED"}.issubset({item["activity_type"] for item in activity})

def test_persona_rules_create_a_distinct_score_and_breakdown():
    with TestClient(app) as client:
        db=SessionLocal(); account=Account(name="Persona test",domain="persona-test.example",icp_score=60); db.add(account); db.flush(); db.add(Prospect(account_id=account.id,name="Taylor",title="Founder & CEO / CTO")); db.commit(); account_id=account.id; db.close()
        assert client.patch(f"/api/accounts/{account_id}/icp",json={"icp_score":60}).status_code==200
        result=client.get("/api/accounts").json()
        item=next(account for account in result if account["domain"]=="persona-test.example")
        assert item["score_breakdown"]["persona"]==92
        assert item["nba_score"]==28
