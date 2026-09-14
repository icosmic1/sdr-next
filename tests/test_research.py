import asyncio
import os
from datetime import datetime
os.environ["DATABASE_URL"]="sqlite:///./data/test_sdr_next.db"
import pytest
from app.database import Base, SessionLocal, engine
from app.models import Account, Prospect, ProspectSignal
from app.research import Finding, extract_findings, extract_google_news_findings, extract_hacker_news_findings, normalize_domain, refresh_prospect

def test_normalize_domain_accepts_domain_and_url():
    assert normalize_domain("Example.com") == "example.com"
    assert normalize_domain("https://www.example.com/about") == "example.com"

@pytest.mark.parametrize("value",["localhost","not a domain","https://"])
def test_normalize_domain_rejects_invalid_values(value):
    with pytest.raises(ValueError): normalize_domain(value)

def test_extract_findings_returns_evidence_and_source():
    html="<html><body><h1>We raised a Series B</h1><p>We are hiring sales people and launching a new product.</p></body></html>"
    results=extract_findings(html,"https://example.com/news")
    kinds={item.kind for item in results}
    assert {"FUNDING","SALES_HIRING","PRODUCT_LAUNCH"}.issubset(kinds)
    assert all(item.url=="https://example.com/news" and item.evidence for item in results)

def test_google_news_rss_results_become_evidence_backed_signals():
    xml="""<rss><channel><item><title>Acme raised a Series B</title><link>https://news.example/acme</link><description>Acme announced funding.</description></item></channel></rss>"""
    results=extract_google_news_findings(xml,"Acme",8)
    assert {item.kind for item in results} == {"FUNDING"}
    assert results[0].url == "https://news.example/acme"

def test_hacker_news_json_results_reject_unrelated_matches_and_uses_safe_fallback():
    payload={"hits":[{"title":"Acme launches a new product","story_text":"","url":"javascript:alert(1)","objectID":"42"},{"title":"Another company raised funding","objectID":"43"}]}
    results=extract_hacker_news_findings(payload,"Acme",8)
    assert {item.kind for item in results} == {"PRODUCT_LAUNCH"}
    assert results[0].url == "https://news.ycombinator.com/item?id=42"

def test_prospect_refresh_persists_person_signals_separately(monkeypatch):
    async def fake_company_refresh(db, account_id): return (0,0,"RESEARCH")
    async def fake_person_research(name, company):
        return [Finding("PERSON_MENTION",f"Public mention of {name}","Alex Smith joined Acme.","https://news.example/alex",.8)]
    monkeypatch.setattr("app.research.refresh_account",fake_company_refresh)
    monkeypatch.setattr("app.research.research_prospect_public",fake_person_research)
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    db=SessionLocal(); account=Account(name="Acme",domain="acme-person.example",last_researched_at=datetime.now()); db.add(account); db.flush(); prospect=Prospect(account_id=account.id,name="Alex Smith",title="VP Sales"); db.add(prospect); db.commit()
    assert asyncio.run(refresh_prospect(db,prospect.id,5))==1
    assert db.query(ProspectSignal).filter_by(prospect_id=prospect.id).count()==1
    assert account.signals==[]
    db.close(); Base.metadata.drop_all(engine)
