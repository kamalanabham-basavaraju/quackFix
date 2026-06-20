from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IncidentRequest(BaseModel):
    incident: str = Field(min_length=3, max_length=20_000)


class ParcleDocument(BaseModel):
    title: str = "Untitled"
    content: str
    reference: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParcleMemoryDocument(BaseModel):
    id: str
    title: str
    content: str
    reference: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class IncidentAnalysis(BaseModel):
    root_cause_hypothesis: str
    affected_components: list[str] = Field(default_factory=list)
    confidence_score: float = Field(ge=0, le=1)
    remediation_strategy: list[str] = Field(default_factory=list)
    hypothesis_reasoning: str
    files_likely_affected: list[str] = Field(default_factory=list)


class IncidentResponse(BaseModel):
    branch_name: str
    files_modified: list[str]
    documentation_updated: bool
    commit_hash: str
    summary: str
    validation: dict[str, Any] = Field(default_factory=dict)
