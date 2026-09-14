from dataclasses import dataclass
from datetime import datetime, timezone

# Seed data only. The application reads the persisted rules on every score.
DEFAULT_RULES = (
    ("weight_icp", "ICP fit weight", "Score weights", .25, None, "Share of the final score from ICP fit."),
    ("weight_signals", "Buying signals weight", "Score weights", .25, None, "Share of the final score from verified signals."),
    ("weight_engagement", "Engagement weight", "Score weights", .20, None, "Share of the final score from engagement."),
    ("weight_timing", "Timing weight", "Score weights", .15, None, "Share of the final score from signal recency."),
    ("weight_persona", "Persona fit weight", "Score weights", .10, None, "Share of the final score from prospect seniority."),
    ("weight_relationship", "Prospect present weight", "Score weights", .05, None, "Share of the final score from having a named prospect."),
    ("signal_sales_hiring", "Sales hiring", "Signal points", 30, "SALES_HIRING", "Points before confidence is applied."),
    ("signal_funding", "Funding", "Signal points", 30, "FUNDING", "Points before confidence is applied."),
    ("signal_leadership", "Leadership change", "Signal points", 22, "LEADERSHIP_CHANGE", "Points before confidence is applied."),
    ("signal_expansion", "Expansion", "Signal points", 18, "EXPANSION", "Points before confidence is applied."),
    ("signal_product", "Product launch", "Signal points", 15, "PRODUCT_LAUNCH", "Points before confidence is applied."),
    ("signal_partnership", "Partnership", "Signal points", 10, "PARTNERSHIP", "Points before confidence is applied."),
    ("persona_cro", "Chief Revenue Officer", "Persona scores", 100, "chief revenue officer", "Prospect title match."),
    ("persona_cro_short", "CRO", "Persona scores", 100, "cro", "Prospect title match."),
    ("persona_vp_sales", "VP Sales", "Persona scores", 95, "vp sales", "Prospect title match."),
    ("persona_vp_sales_long", "Vice President of Sales", "Persona scores", 95, "vice president of sales", "Prospect title match."),
    ("persona_head_sales", "Head of Sales", "Persona scores", 90, "head of sales", "Prospect title match."),
    ("persona_founder_ceo", "Founder and CEO", "Persona scores", 92, "founder & ceo", "Prospect title match."),
    ("persona_ceo", "Chief Executive Officer / CEO", "Persona scores", 85, "ceo", "Prospect title match."),
    ("persona_cto", "Chief Technology Officer / CTO", "Persona scores", 80, "cto", "Prospect title match."),
    ("persona_vp_product", "VP Product", "Persona scores", 78, "vp of product", "Prospect title match."),
    ("persona_product_management", "Product management", "Persona scores", 70, "product management", "Prospect title match."),
    ("persona_strategy", "Strategy leader", "Persona scores", 72, "chief strategy", "Prospect title match."),
    ("persona_revops", "Revenue Operations", "Persona scores", 85, "revenue operations", "Prospect title match."),
    ("persona_director_revops", "Director of RevOps", "Persona scores", 85, "director of revops", "Prospect title match."),
    ("persona_sales_manager", "Sales Manager", "Persona scores", 65, "sales manager", "Prospect title match."),
    ("persona_ae", "Account Executive", "Persona scores", 55, "account executive", "Prospect title match."),
    ("persona_default", "Default persona", "Persona scores", 35, None, "Score when no title rule matches."),
    ("engagement_reply", "Reply points", "Engagement", 45, None, "Points for a replied prospect."),
    ("engagement_open", "Email-open points", "Engagement", 15, None, "Points per counted email open."),
    ("engagement_max_opens", "Maximum counted opens", "Engagement", 3, None, "Email opens included in the score."),
    ("relationship_prospect", "Named prospect score", "Engagement", 25, None, "Raw relationship score when a prospect exists."),
    ("timing_no_signal", "No-signal timing score", "Timing", 20, None, "Timing score without verified signals."),
    ("timing_floor", "Minimum fresh timing score", "Timing", 30, None, "Lowest score for a verified signal."),
    ("timing_daily_decay", "Daily timing decay", "Timing", 3, None, "Points removed for each day since a signal was seen."),
    ("timing_minimum", "Minimum aged timing score", "Timing", 10, None, "Floor applied before averaging aged signals."),
    ("action_call_score", "Call score threshold", "Action thresholds", 85, None, "Minimum score for a call recommendation."),
    ("action_call_opens", "Call email-open threshold", "Action thresholds", 2, None, "Email opens needed for a call without a phone number."),
    ("action_email_score", "Personalized email threshold", "Action thresholds", 75, None, "Minimum score for a personalized email."),
    ("action_research_score", "Research threshold", "Action thresholds", 45, None, "Minimum score for research."),
)

@dataclass
class ScoreResult:
    score: int; action: str; icp: int; signals: int; engagement: int; timing: int; persona: int

def rule_map(rules=None) -> dict[str, float]:
    values={key:value for key, _, _, value, _, _ in DEFAULT_RULES}
    values.update({rule.key:rule.value for rule in (rules or ())})
    return values

def persona_score(title: str, rules=None) -> int:
    values=rule_map(rules); records=[(rule.match_text,rule.value) for rule in (rules or ()) if rule.category=="Persona scores" and rule.match_text]
    if not records: records=[(match,value) for _,_,category,value,match,_ in DEFAULT_RULES if category=="Persona scores" and match]
    matches=[score for pattern,score in records if pattern.lower() in title.lower().strip()]
    if matches: return round(max(matches))
    return round(values["persona_default"])

def choose_action(score: int, replied: bool=False, opens: int=0, phone: bool=False, rules=None) -> str:
    values=rule_map(rules)
    if replied: return "FOLLOW_UP"
    if score >= values["action_call_score"] and (phone or opens >= values["action_call_opens"]): return "CALL"
    if score >= values["action_email_score"]: return "PERSONALIZED_EMAIL"
    if score >= values["action_research_score"]: return "RESEARCH"
    return "DEPRIORITIZE"

def calculate(account, rules=None) -> ScoreResult:
    values=rule_map(rules); prospects=list(account.prospects); prospect=prospects[0] if prospects else None
    persona=persona_score(prospect.title,rules) if prospect else round(values["persona_default"])
    engagement=min(100,(values["engagement_reply"] if prospect and prospect.replied else 0)+(min(prospect.email_open_count,values["engagement_max_opens"])*values["engagement_open"] if prospect else 0))
    points={rule.match_text:rule.value for rule in (rules or ()) if rule.category=="Signal points" and rule.match_text}
    if not points: points={match:value for _,_,category,value,match,_ in DEFAULT_RULES if category=="Signal points"}
    signal_total=min(100,sum(points.get(signal.signal_type,0)*signal.confidence for signal in account.signals if signal.status=="VERIFIED"))
    fresh=[signal for signal in account.signals if signal.status=="VERIFIED"]
    timing=values["timing_no_signal"] if not fresh else max(values["timing_floor"],min(100,int(sum(max(values["timing_minimum"],100-(datetime.now(timezone.utc)-_aware(signal.last_seen_at)).days*values["timing_daily_decay"]) for signal in fresh)/len(fresh))))
    relationship=values["relationship_prospect"] if prospect else 0
    score=round(account.icp_score*values["weight_icp"]+signal_total*values["weight_signals"]+engagement*values["weight_engagement"]+timing*values["weight_timing"]+persona*values["weight_persona"]+relationship*values["weight_relationship"])
    score=min(100,max(0,score))
    return ScoreResult(score,choose_action(score,bool(prospect and prospect.replied),prospect.email_open_count if prospect else 0,bool(prospect and prospect.phone),rules),account.icp_score,round(signal_total),round(engagement),round(timing),persona)

def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
