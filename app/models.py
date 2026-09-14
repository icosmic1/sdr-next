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
