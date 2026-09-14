from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

def utcnow(): return datetime.now(timezone.utc)

class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    employee_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    icp_score: Mapped[int] = mapped_column(Integer, default=50)
    nba_score: Mapped[int] = mapped_column(Integer, default=0)
    previous_score: Mapped[int] = mapped_column(Integer, default=0)
    recommended_action: Mapped[str] = mapped_column(String(40), default="RESEARCH")
    last_researched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    prospects: Mapped[list["Prospect"]] = relationship(back_populates="account", cascade="all, delete-orphan")
    signals: Mapped[list["Signal"]] = relationship(back_populates="account", cascade="all, delete-orphan")
    activities: Mapped[list["Activity"]] = relationship(back_populates="account", cascade="all, delete-orphan")

class Prospect(Base):
    __tablename__ = "prospects"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email_open_count: Mapped[int] = mapped_column(Integer, default=0)
    replied: Mapped[bool] = mapped_column(Boolean, default=False)
    account: Mapped[Account] = relationship(back_populates="prospects")
    research_state: Mapped["ProspectResearchState | None"] = relationship(back_populates="prospect", uselist=False, cascade="all, delete-orphan")
    person_signals: Mapped[list["ProspectSignal"]] = relationship(back_populates="prospect", cascade="all, delete-orphan")
    follow_ups: Mapped[list["FollowUpTask"]] = relationship(back_populates="prospect", cascade="all, delete-orphan")
    contact_preference: Mapped["ProspectPreference | None"] = relationship(back_populates="prospect", uselist=False, cascade="all, delete-orphan")

    @property
    def do_not_contact(self) -> bool:
        return bool(self.contact_preference and self.contact_preference.do_not_contact)

class FollowUpTask(Base):
    __tablename__ = "follow_up_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    prospect_id: Mapped[int] = mapped_column(ForeignKey("prospects.id"), index=True)
    owner: Mapped[str] = mapped_column(String(120), default="Manvi")
    next_step: Mapped[str] = mapped_column(String(500))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), default="OPEN", index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    prospect: Mapped["Prospect"] = relationship(back_populates="follow_ups")

class ProspectPreference(Base):
    __tablename__ = "prospect_preferences"
    prospect_id: Mapped[int] = mapped_column(ForeignKey("prospects.id"), primary_key=True)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    prospect: Mapped["Prospect"] = relationship(back_populates="contact_preference")

class ProspectResearchState(Base):
    __tablename__ = "prospect_research_states"
    id: Mapped[int] = mapped_column(primary_key=True)
    prospect_id: Mapped[int] = mapped_column(ForeignKey("prospects.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="NEVER")
    last_researched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    prospect: Mapped["Prospect"] = relationship(back_populates="research_state")
    signals: Mapped[list["ProspectSignal"]] = relationship(back_populates="research_state", cascade="all, delete-orphan")

class ProspectSignal(Base):
    __tablename__ = "prospect_signals"
    __table_args__ = (UniqueConstraint("prospect_id", "source_url", name="uq_prospect_signal_source"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    prospect_id: Mapped[int] = mapped_column(ForeignKey("prospects.id"), index=True)
    research_state_id: Mapped[int] = mapped_column(ForeignKey("prospect_research_states.id"), index=True)
    signal_type: Mapped[str] = mapped_column(String(60), default="PERSON_MENTION")
    summary: Mapped[str] = mapped_column(String(500))
    evidence: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(String(1000))
    confidence: Mapped[float] = mapped_column(Float)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    prospect: Mapped["Prospect"] = relationship(back_populates="person_signals")
    research_state: Mapped["ProspectResearchState"] = relationship(back_populates="signals")

class ResearchJob(Base):
    __tablename__ = "research_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(30))
    trigger: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    prospect_id: Mapped[int | None] = mapped_column(ForeignKey("prospects.id"), nullable=True, index=True)
    signals_found: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("account_id", "signal_type", "source_url", name="uq_signal_evidence"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    signal_type: Mapped[str] = mapped_column(String(60))
    summary: Mapped[str] = mapped_column(String(500))
    evidence: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(String(1000))
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), default="VERIFIED")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    account: Mapped[Account] = relationship(back_populates="signals")

class Activity(Base):
    __tablename__ = "activities"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), index=True, nullable=True)
    activity_type: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    account: Mapped[Account | None] = relationship(back_populates="activities")

class ScoringRule(Base):
    __tablename__ = "scoring_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(60), index=True)
    value: Mapped[float] = mapped_column(Float)
    match_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str] = mapped_column(String(400))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
