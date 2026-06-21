from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProduckAnnotation(BaseModel):
    index: int = 0
    type: str | None = None
    text: str | None = None
    interpreted_text: str | None = None
    anchor: dict[str, Any] = Field(default_factory=dict)
    anchor_percent: dict[str, Any] = Field(default_factory=dict)
    selectors: list[Any] = Field(default_factory=list)
    element: Any | None = None
    locator_confidence: str | None = None


class ProduckTicket(BaseModel):
    ticket_id: str
    title: str = "Produck feedback"
    description: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    route: str | None = None
    page_url: str | None = None
    annotations: list[ProduckAnnotation] = Field(default_factory=list)
    snapshot_summary: dict[str, Any] = Field(default_factory=dict)
    design_doc: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)
    brief_markdown: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class NormalizedProduckRequest(BaseModel):
    ticket_id: str
    classification: Literal["bug", "feature", "ux", "documentation", "onboarding", "question", "unknown"]
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    summary: str
    problem_statement: str
    reproduction_steps: list[str] = Field(default_factory=list)
    affected_route: str | None = None
    suggested_fix: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)
    context: dict[str, Any] = Field(default_factory=dict)

    def to_parcle_query(self) -> str:
        location = self.context.get("location_evidence") or ""
        return f"""Find repo documentation relevant to this Produck feedback.

Ticket: {self.ticket_id}
Classification: {self.classification}
Summary: {self.summary}
Route: {self.affected_route or "unknown"}
Problem: {self.problem_statement}
Location evidence:
{location}
"""

    def to_incident_prompt(self) -> str:
        steps = "\n".join(f"- {step}" for step in self.reproduction_steps) or "- Not provided"
        location = self.context.get("location_evidence")
        location_section = f"\nLocation evidence for pinpointing the UI:\n{location}\n" if location else ""
        return f"""Produck feedback ticket {self.ticket_id}: {self.summary}

Classification: {self.classification}
Priority: {self.priority}
Affected route: {self.affected_route or "unknown"}

Problem:
{self.problem_statement}

Reproduction / evidence:
{steps}
{location_section}

Suggested fix:
{self.suggested_fix or "Infer the smallest safe fix from the available context."}

Use this as a repo-level code-change request only if the Produck evidence is actionable. If the element or behavior is
too uncertain, write an investigation note in the Parcle memory incident record instead of guessing."""


class ProduckTicketState(BaseModel):
    ticket_id: str
    status: Literal["seen", "processing", "processed", "failed"] = "seen"
    last_seen: str
    processed_at: str | None = None
    workflow_run_id: str | None = None
    fingerprint: str = ""
    error: str | None = None


class ProduckPollResult(BaseModel):
    checked_at: datetime
    fetched: int = 0
    processed: int = 0
    duplicates: int = 0
    failures: int = 0
    triggered: int = 0
    tickets: list[str] = Field(default_factory=list)
