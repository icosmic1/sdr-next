import asyncio, ipaddress, re, socket
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from .config import get_settings
from .models import Account, Signal
from .scoring import calculate

PATTERNS = {
 "SALES_HIRING": (r"\b(hiring|open positions?|join our team|careers?)\b", "Active hiring language found"),
 "FUNDING": (r"\b(series [a-e]|funding round|raised|investment)\b", "Funding or investment announcement found"),
 "LEADERSHIP_CHANGE": (r"\b(appointed|joins? as|new (cro|chief revenue|vp of sales|vice president))\b", "Leadership change found"),
 "EXPANSION": (r"\b(expand(?:s|ed|ing)?|new office|new market|international growth)\b", "Expansion signal found"),
 "PRODUCT_LAUNCH": (r"\b(launch(?:es|ed|ing)?|new product|introduc(?:e|es|ed|ing))\b", "Product launch signal found"),
 "PARTNERSHIP": (r"\b(partner(?:s|ed|ship)?|collaboration|strategic alliance)\b", "Partnership signal found"),
}
PATHS = ("/", "/news", "/newsroom", "/blog", "/careers", "/jobs")

@dataclass
class Finding:
    kind: str; summary: str; evidence: str; url: str; confidence: float

def normalize_domain(raw: str) -> str:
    raw = raw.strip().lower()
    if "://" not in raw: raw = "https://" + raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").removeprefix("www.")
    if not host or "." not in host or not re.fullmatch(r"[a-z0-9.-]+", host): raise ValueError("invalid company domain")
    return host

def assert_public_host(host: str) -> None:
    try: addresses = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc: raise ValueError("domain could not be resolved") from exc
    for item in addresses:
        ip = ipaddress.ip_address(item[4][0])
        if not ip.is_global: raise ValueError("private or reserved network destinations are blocked")

def extract_findings(html: str, url: str) -> list[Finding]:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script","style","noscript"]): node.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())[:100_000]
    findings=[]
    for kind,(pattern,summary) in PATTERNS.items():
        match=re.search(pattern,text,re.I)
        if match:
            start=max(0,match.start()-120); end=min(len(text),match.end()+180)
            findings.append(Finding(kind,summary,text[start:end][:400],url,.85 if kind in {"SALES_HIRING","FUNDING"} else .72))
    return findings

async def research_domain(domain: str) -> list[Finding]:
    assert_public_host(domain)
    settings=get_settings(); base=f"https://{domain}"
    limits=httpx.Limits(max_connections=3,max_keepalive_connections=2)
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds,follow_redirects=True,limits=limits,headers={"User-Agent":settings.user_agent}) as client:
        async def fetch(path):
            url=urljoin(base,path)
            try:
                response=await client.get(url)
                final=response.url
                if final.host and final.host.removeprefix("www.") != domain: return []
                if response.status_code==200 and "text/html" in response.headers.get("content-type",""): return extract_findings(response.text,str(final))
            except httpx.HTTPError: pass
            return []
        pages=await asyncio.gather(*(fetch(p) for p in PATHS[:settings.max_research_pages]))
    unique={}
    for finding in [x for page in pages for x in page]: unique[(finding.kind,finding.url)]=finding
    return list(unique.values())

async def refresh_account(db: Session, account_id: int) -> tuple[int,int,str]:
    account=db.get(Account,account_id)
    if not account: raise ValueError("account not found")
    account.status="RESEARCHING"; db.commit()
    try:
        findings=await research_domain(account.domain); now=datetime.now(timezone.utc)
        for f in findings:
            signal=db.query(Signal).filter_by(account_id=account.id,signal_type=f.kind,source_url=f.url).one_or_none()
            if signal:
                signal.summary=f.summary; signal.evidence=f.evidence; signal.confidence=f.confidence; signal.last_seen_at=now; signal.status="VERIFIED"
            else: db.add(Signal(account_id=account.id,signal_type=f.kind,summary=f.summary,evidence=f.evidence,source_url=f.url,confidence=f.confidence,last_seen_at=now))
        account.previous_score=account.nba_score
        account.last_researched_at=now; account.status="READY"
        db.flush(); result=calculate(account); account.nba_score=result.score; account.recommended_action=result.action; db.commit(); db.refresh(account)
        return len(findings),account.nba_score,account.recommended_action
    except Exception:
        account.status="RESEARCH_FAILED"; db.commit(); raise
