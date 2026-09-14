from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class SignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    signal_type: str
    summary: str
    evidence: str
    source_url: str
    confidence: float
    status: str
    detected_at: datetime
    last_seen_at: datetime

class ProspectSignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    signal_type: str
    summary: str
    evidence: str
    source_url: str
    confidence: float
    detected_at: datetime
    last_seen_at: datetime

class ProspectResearchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    status: str
    last_researched_at: datetime | None
    error_message: str | None
    signals: list[ProspectSignalOut]

class FollowUpOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    prospect_id: int
    owner: str
    next_step: str
    due_at: datetime
    status: str
    completed_at: datetime | None
    created_at: datetime

class FollowUpCreate(BaseModel):
    owner: str = Field(default="Manvi", min_length=1, max_length=120)
    next_step: str = Field(min_length=3, max_length=500)
    due_at: datetime

class FollowUpUpdate(BaseModel):
    status: Literal["OPEN", "DONE"] | None = None
    due_at: datetime | None = None
    owner: str | None = Field(default=None, min_length=1, max_length=120)
    next_step: str | None = Field(default=None, min_length=3, max_length=500)

class ProspectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    title: str
    email: str | None
    phone: str | None
    email_open_count: int
    replied: bool
    research_state: ProspectResearchOut | None
    follow_ups: list[FollowUpOut]
    do_not_contact: bool

class ScoreBreakdownOut(BaseModel):
    icp: int
    signals: int
    engagement: int
    timing: int
    persona: int

class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    domain: str
    industry: str | None
    employee_count: int | None
    status: str
    icp_score: int
    nba_score: int
    previous_score: int
    recommended_action: str
    last_researched_at: datetime | None
    prospects: list[ProspectOut]
    signals: list[SignalOut]
    score_breakdown: ScoreBreakdownOut

class ImportResult(BaseModel):
    imported: int
    updated: int
    rejected: list[str]
    research_started: bool

class RefreshResult(BaseModel):
    account_id: int
    status: str
    signals_found: int
    score: int
    action: str

class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    account_id: int | None
    activity_type: str
    detail: str
    created_at: datetime

class ScoringRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    label: str
    category: str
    value: float
    match_text: str | None
    description: str
    updated_at: datetime

class ScoringRuleUpdate(BaseModel):
    key: str
    value: float

class ResearchJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    scope: str
    trigger: str
    status: str
    account_id: int
    prospect_id: int | None
    signals_found: int
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

class ResearchStatusOut(BaseModel):
    queued: int
    running: int
    last_completed_at: datetime | None
    next_scheduled_at: datetime | None
    interval_minutes: int

class OutreachOut(BaseModel):
    prospect_id: int
    provider: str
    model: str
    subject: str
    opening_line: str
    email_body: str
    call_talk_track: str
    source_urls: list[str]

class IcpUpdate(BaseModel):
    icp_score: int
