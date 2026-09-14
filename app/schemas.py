from datetime import datetime
from pydantic import BaseModel, ConfigDict

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

class ProspectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    title: str
    email: str | None
    phone: str | None
    email_open_count: int
    replied: bool

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
