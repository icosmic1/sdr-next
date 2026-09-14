import asyncio, ipaddress, re, socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, urljoin, urlparse
from xml.etree import ElementTree
import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import get_settings
from .models import Account, Activity, Prospect, ProspectResearchState, ProspectSignal, ScoringRule, Signal
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

def extract_findings_from_text(text: str, url: str, confidence: float = .72) -> list[Finding]:
    """Turn a trusted page or public-API result into evidence-backed signals."""
    text = " ".join(text.split())[:100_000]
    findings=[]
    for kind,(pattern,summary) in PATTERNS.items():
        match=re.search(pattern,text,re.I)
        if match:
            start=max(0,match.start()-120); end=min(len(text),match.end()+180)
            findings.append(Finding(kind,summary,text[start:end][:400],url,confidence if kind not in {"SALES_HIRING","FUNDING"} else min(.9, confidence + .13)))
    return findings

def extract_findings(html: str, url: str) -> list[Finding]:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script","style","noscript"]): node.decompose()
    return extract_findings_from_text(soup.get_text(" ", strip=True), url, .72)

def external_http_url(value: str | None, fallback: str) -> str:
    """Only persist navigable public links returned by external providers."""
    parsed=urlparse(value or "")
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else fallback

def extract_google_news_findings(xml: str, company_name: str, limit: int) -> list[Finding]:
    """Parse Google's public RSS response without trusting feed HTML as markup."""
    try: root=ElementTree.fromstring(xml)
    except ElementTree.ParseError: return []
    findings=[]
    for item in root.findall("./channel/item")[:limit]:
        title=(item.findtext("title") or "").strip()
        description=BeautifulSoup(item.findtext("description") or "", "html.parser").get_text(" ", strip=True)
        link=external_http_url(item.findtext("link"), "https://news.google.com/")
        # Google News may return broad, unrelated matches for short company names.
        if company_name.lower() not in f"{title} {description}".lower(): continue
        findings.extend(extract_findings_from_text(f"{title}. {description}", link, .78))
    return findings

def extract_hacker_news_findings(payload: dict, company_name: str, limit: int) -> list[Finding]:
    """Parse the public HN Algolia JSON API and keep only company-specific stories."""
    findings=[]
    for hit in payload.get("hits", [])[:limit]:
        title=str(hit.get("title") or "")
        story_text=BeautifulSoup(str(hit.get("story_text") or ""), "html.parser").get_text(" ", strip=True)
        if company_name.lower() not in f"{title} {story_text}".lower(): continue
        fallback=f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
        link=external_http_url(hit.get("url"), fallback)
        findings.extend(extract_findings_from_text(f"{title}. {story_text}", link, .68))
    return findings

async def research_external_news(client: httpx.AsyncClient, company_name: str) -> list[Finding]:
    """Fetch live public news APIs. Provider failures never block company-site research."""
    settings=get_settings(); tasks=[]
    if settings.google_news_enabled:
        url="https://news.google.com/rss/search?q=" + quote_plus(f'"{company_name}"') + "&hl=en-US&gl=US&ceid=US:en"
        tasks.append(client.get(url))
    if settings.hacker_news_enabled:
        url="https://hn.algolia.com/api/v1/search?tags=story&hitsPerPage=" + str(settings.max_external_news_results) + "&query=" + quote_plus(company_name)
        tasks.append(client.get(url))
    if not tasks: return []
    responses=await asyncio.gather(*tasks, return_exceptions=True)
    findings=[]
    for response in responses:
        if isinstance(response, Exception) or response.status_code != 200: continue
        try:
            if "news.google.com" in response.url.host:
                findings.extend(extract_google_news_findings(response.text, company_name, settings.max_external_news_results))
            elif "hn.algolia.com" in response.url.host:
                findings.extend(extract_hacker_news_findings(response.json(), company_name, settings.max_external_news_results))
        except (ValueError, TypeError):
            continue
    return findings

def extract_person_mentions(text: str, url: str, prospect_name: str, company_name: str, confidence: float) -> list[Finding]:
    """Keep only public results that explicitly mention both the person and company."""
    clean=BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    if prospect_name.lower() not in clean.lower() or company_name.lower() not in clean.lower(): return []
    return [Finding("PERSON_MENTION", f"Public mention of {prospect_name}", clean[:400], url, confidence)]

async def research_prospect_public(prospect_name: str, company_name: str) -> list[Finding]:
    """Fetch public person-plus-company mentions; this deliberately avoids restricted networks."""
    settings=get_settings(); query=f'"{prospect_name}" "{company_name}"'; tasks=[]
    limits=httpx.Limits(max_connections=2,max_keepalive_connections=1)
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds,follow_redirects=True,limits=limits,headers={"User-Agent":settings.user_agent}) as client:
        if settings.google_news_enabled:
            tasks.append(client.get("https://news.google.com/rss/search?q="+quote_plus(query)+"&hl=en-US&gl=US&ceid=US:en"))
        if settings.hacker_news_enabled:
            tasks.append(client.get("https://hn.algolia.com/api/v1/search?tags=story&hitsPerPage="+str(settings.max_external_news_results)+"&query="+quote_plus(query)))
        if not tasks: return []
        responses=await asyncio.gather(*tasks,return_exceptions=True)
    findings=[]
    for response in responses:
        if isinstance(response,Exception) or response.status_code!=200: continue
        try:
            if "news.google.com" in response.url.host:
                root=ElementTree.fromstring(response.text)
                for item in root.findall("./channel/item")[:settings.max_external_news_results]:
                    title=(item.findtext("title") or "").strip(); description=item.findtext("description") or ""
                    findings.extend(extract_person_mentions(f"{title}. {description}",external_http_url(item.findtext("link"),"https://news.google.com/"),prospect_name,company_name,.78))
            elif "hn.algolia.com" in response.url.host:
                for hit in response.json().get("hits",[])[:settings.max_external_news_results]:
                    title=str(hit.get("title") or ""); story=str(hit.get("story_text") or "")
                    url=external_http_url(hit.get("url"),f"https://news.ycombinator.com/item?id={hit.get('objectID','')}")
                    findings.extend(extract_person_mentions(f"{title}. {story}",url,prospect_name,company_name,.68))
        except (TypeError,ValueError,ElementTree.ParseError): continue
    return list({finding.url:finding for finding in findings}.values())

async def research_domain(domain: str, company_name: str | None = None) -> list[Finding]:
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
        page_results, external_results=await asyncio.gather(
            asyncio.gather(*(fetch(p) for p in PATHS[:settings.max_research_pages])),
            research_external_news(client, company_name) if company_name else asyncio.sleep(0, result=[]),
        )
    unique={}
    for finding in [x for page in page_results for x in page] + external_results: unique[(finding.kind,finding.url)]=finding
    return list(unique.values())

async def refresh_account(db: Session, account_id: int) -> tuple[int,int,str]:
    account=db.get(Account,account_id)
    if not account: raise ValueError("account not found")
    account.status="RESEARCHING"; db.commit()
    try:
        findings=await research_domain(account.domain, account.name); now=datetime.now(timezone.utc)
        for f in findings:
            signal=db.query(Signal).filter_by(account_id=account.id,signal_type=f.kind,source_url=f.url).one_or_none()
            if signal:
                signal.summary=f.summary; signal.evidence=f.evidence; signal.confidence=f.confidence; signal.last_seen_at=now; signal.status="VERIFIED"
            else: db.add(Signal(account_id=account.id,signal_type=f.kind,summary=f.summary,evidence=f.evidence,source_url=f.url,confidence=f.confidence,last_seen_at=now))
        account.previous_score=account.nba_score
        account.last_researched_at=now; account.status="READY"
        rules=list(db.scalars(select(ScoringRule)))
        db.flush(); result=calculate(account,rules); account.nba_score=result.score; account.recommended_action=result.action
        db.add(Activity(account_id=account.id,activity_type="RESEARCH_COMPLETED",detail=f"Research completed with {len(findings)} verified signals; score is now {account.nba_score}."))
        db.commit(); db.refresh(account)
        return len(findings),account.nba_score,account.recommended_action
    except Exception:
        account.status="RESEARCH_FAILED"; db.commit(); raise

async def refresh_prospect(db: Session, prospect_id: int, company_freshness_minutes: int) -> int:
    """Refresh company context when stale, then collect separate public evidence for one prospect."""
    prospect=db.get(Prospect,prospect_id)
    if not prospect: raise ValueError("prospect not found")
    account=db.get(Account,prospect.account_id)
    state=db.scalar(select(ProspectResearchState).where(ProspectResearchState.prospect_id==prospect.id))
    if not state:
        state=ProspectResearchState(prospect_id=prospect.id,status="RESEARCHING"); db.add(state)
    state.status="RESEARCHING"; state.error_message=None; db.commit()
    try:
        now=datetime.now(timezone.utc); last_company_refresh=account.last_researched_at
        if last_company_refresh and last_company_refresh.tzinfo is None: last_company_refresh=last_company_refresh.replace(tzinfo=timezone.utc)
        if not last_company_refresh or last_company_refresh < now-timedelta(minutes=company_freshness_minutes):
            await refresh_account(db,account.id)
        findings=await research_prospect_public(prospect.name,account.name); now=datetime.now(timezone.utc)
        db.refresh(state)
        for finding in findings:
            signal=db.query(ProspectSignal).filter_by(prospect_id=prospect.id,source_url=finding.url).one_or_none()
            if signal:
                signal.summary=finding.summary; signal.evidence=finding.evidence; signal.confidence=finding.confidence; signal.last_seen_at=now
            else:
                db.add(ProspectSignal(prospect_id=prospect.id,research_state_id=state.id,signal_type=finding.kind,summary=finding.summary,evidence=finding.evidence,source_url=finding.url,confidence=finding.confidence,last_seen_at=now))
        state.status="READY"; state.last_researched_at=now; state.error_message=None
        db.add(Activity(account_id=account.id,activity_type="PERSON_RESEARCH_COMPLETED",detail=f"Public person research for {prospect.name} completed with {len(findings)} verified mentions."))
        db.commit(); return len(findings)
    except Exception as exc:
        state.status="RESEARCH_FAILED"; state.error_message=str(exc)[:500]
        db.add(Activity(account_id=account.id,activity_type="PERSON_RESEARCH_FAILED",detail=f"Public person research for {prospect.name} failed.")); db.commit(); raise
