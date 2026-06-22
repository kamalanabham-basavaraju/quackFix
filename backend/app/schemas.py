from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    timestamp: datetime

    model_config = {"from_attributes": True}


class ExecutionOut(BaseModel):
    id: str
    conversation_id: str
    status: str
    stage: str
    started_at: datetime
    completed_at: datetime | None
    summary: str | None
    branch_name: str | None
    commit_hash: str | None
    pull_request_url: str | None
    incident_record_path: str | None
    files_modified: list[str]
    documentation_updated: bool
    validation: dict[str, Any]
    raw_response: dict[str, Any]
    error: str | None

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: str
    title: str
    severity: str
    category: str | None
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut] = []
    executions: list[ExecutionOut] = []

    model_config = {"from_attributes": True}


class ConversationCreate(BaseModel):
    title: str = "New incident"
    severity: str = "medium"
    category: str | None = None
    tags: list[str] = Field(default_factory=list)


class IncidentSubmit(BaseModel):
    incident: str = Field(min_length=3, max_length=20_000)
    conversation_id: str | None = None
    employee_portal_path: str | None = None
    severity: str = "medium"
    category: str | None = None
    tags: list[str] = Field(default_factory=list)


class IncidentSubmitResponse(BaseModel):
    conversation: ConversationOut
    execution: ExecutionOut


class DashboardOut(BaseModel):
    total_incidents: int
    successful_resolutions: int
    failed_resolutions: int
    open_prs: int
    average_resolution_seconds: float
    incidents_by_day: list[dict[str, Any]]
    success_rate: list[dict[str, Any]]
    resolution_duration: list[dict[str, Any]]


class SearchResult(BaseModel):
    conversation_id: str
    title: str
    snippet: str
    status: str | None = None
    updated_at: datetime


class ProduckFetchSetting(BaseModel):
    enabled: bool


class ProduckFetchSettingOut(BaseModel):
    enabled: bool
    updated_at: datetime | None = None


class TargetRepoSetting(BaseModel):
    employee_portal_path: str


class TargetRepoSettingOut(BaseModel):
    employee_portal_path: str
    updated_at: datetime | None = None


class ProduckPollHistoryResponse(BaseModel):
    checked_at: str | None = None
    fetched: int = 0
    added: int = 0
    updated: int = 0
    skipped_processed: int = 0
    failures: int = 0
    conversations: list[ConversationOut] = []


class ProduckTriggerResponse(BaseModel):
    conversation: ConversationOut
    execution: ExecutionOut
