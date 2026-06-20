"""Serializable state passed through the incident-resolution graph."""

from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    incident: str
    run_id: str
    started_at: str
    parcle_documents: list[dict[str, Any]]
    memory_references: list[str]
    root_cause_hypothesis: str
    affected_components: list[str]
    confidence_score: float
    remediation_strategy: list[str]
    hypothesis_reasoning: str
    files_likely_affected: list[str]
    enterpro_prompt: str
    project_path: str
    branch_name: str
    enterpro_result: dict[str, Any]
    files_modified: list[str]
    validation: dict[str, Any]
    decision_log_path: str
    decision_entry: str
    parcle_decision_sync: dict[str, Any]
    commit_hash: str
    documentation_updated: bool
    summary: str
    errors: list[str]
