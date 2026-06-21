from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def new_id() -> str:
    return str(uuid4())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(240))
    severity: Mapped[str] = mapped_column(String(32), default="medium")
    category: Mapped[str] = mapped_column(String(80), nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.timestamp",
        uselist=True,
    )
    executions = relationship(
        "IncidentExecution",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="IncidentExecution.started_at",
        uselist=True,
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(24))
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    conversation = relationship("Conversation", back_populates="messages", uselist=False)


class IncidentExecution(Base):
    __tablename__ = "incident_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    stage: Mapped[str] = mapped_column(String(80), default="queued")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    branch_name: Mapped[str] = mapped_column(String(255), nullable=True)
    commit_hash: Mapped[str] = mapped_column(String(80), nullable=True)
    pull_request_url: Mapped[str] = mapped_column(Text, nullable=True)
    incident_record_path: Mapped[str] = mapped_column(Text, nullable=True)
    files_modified: Mapped[list] = mapped_column(JSON, default=list)
    documentation_updated: Mapped[bool] = mapped_column(Boolean, default=False)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_response: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, nullable=True)

    conversation = relationship("Conversation", back_populates="executions", uselist=False)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
