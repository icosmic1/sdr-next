from dataclasses import dataclass
from datetime import datetime, timezone

PERSONA = {"chief revenue officer":100,"cro":100,"vp sales":95,"vice president of sales":95,"head of sales":90,"director of revops":85,"revenue operations":85,"sales manager":65,"account executive":55}
SIGNAL_POINTS = {"SALES_HIRING":30,"FUNDING":30,"LEADERSHIP_CHANGE":22,"EXPANSION":18,"PRODUCT_LAUNCH":15,"PARTNERSHIP":10}

@dataclass
class ScoreResult:
    score: int
    action: str
    icp: int
    signals: int
    engagement: int
    timing: int
    persona: int

def persona_score(title: str) -> int:
    value = title.lower().strip()
    for key, score in PERSONA.items():
        if key in value: return score
    return 35

def choose_action(score: int, replied: bool = False, opens: int = 0, phone: bool = False) -> str:
    if replied: return "FOLLOW_UP"
    if score >= 85 and (phone or opens >= 2): return "CALL"
    if score >= 75: return "PERSONALIZED_EMAIL"
    if score >= 45: return "RESEARCH"
    return "DEPRIORITIZE"

def calculate(account) -> ScoreResult:
    prospects = list(account.prospects)
    prospect = prospects[0] if prospects else None
    persona = persona_score(prospect.title) if prospect else 30
    engagement = min(100, (45 if prospect and prospect.replied else 0) + (min(prospect.email_open_count, 3) * 15 if prospect else 0))
    signal_total = min(100, sum(SIGNAL_POINTS.get(s.signal_type, 5) * s.confidence for s in account.signals if s.status == "VERIFIED"))
    fresh = [s for s in account.signals if s.status == "VERIFIED"]
    timing = 20 if not fresh else max(30, min(100, int(sum(max(10, 100 - (datetime.now(timezone.utc) - _aware(s.last_seen_at)).days * 3) for s in fresh) / len(fresh))))
    icp = account.icp_score
    relationship = 25 if prospect else 0
    score = round(icp*.25 + signal_total*.25 + engagement*.20 + timing*.15 + persona*.10 + relationship*.05)
    score = min(100, max(0, score))
    return ScoreResult(score, choose_action(score, bool(prospect and prospect.replied), prospect.email_open_count if prospect else 0, bool(prospect and prospect.phone)), icp, round(signal_total), engagement, timing, persona)

def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
