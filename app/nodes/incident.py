from __future__ import annotations

import logging
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from app.graph.state import AgentState
from app.integrations.git import GitClient
from app.models.incident import IncidentAnalysis, ParcleDocument, ParcleMemoryDocument
from app.services.container import WorkflowServices

logger = logging.getLogger(__name__)
Node = Callable[[AgentState], dict[str, Any]]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _documents(state: AgentState) -> list[ParcleDocument]:
    return [ParcleDocument.model_validate(item) for item in state.get("parcle_documents", [])]


def build_nodes(services: WorkflowServices) -> dict[str, Node]:
    project_path = services.settings.employee_portal_path
    git = GitClient(project_path)

    def receive_incident(state: AgentState) -> dict[str, Any]:
        incident = state.get("incident", "").strip()
        if not incident:
            raise ValueError("incident must not be empty")
        logger.info("Incident run started", extra={"incident_run_id": state.get("run_id")})
        return {
            "incident": incident,
            "run_id": state.get("run_id") or str(uuid4()),
            "started_at": state.get("started_at") or _utc_now().isoformat(),
            "project_path": str(project_path),
            "errors": [],
        }

    def search_parcle(state: AgentState) -> dict[str, Any]:
        documents = services.parcle.search(state["incident"])
        return {
            "parcle_documents": [document.model_dump(mode="json") for document in documents],
            "memory_references": [document.reference for document in documents if document.reference],
        }

    def analyze_incident(state: AgentState) -> dict[str, Any]:
        analysis = services.groq.analyze(state["incident"], _documents(state))
        return analysis.model_dump()

    def generate_enterpro_prompt(state: AgentState) -> dict[str, Any]:
        analysis = IncidentAnalysis.model_validate(state)
        prompt = services.groq.generate_enterpro_prompt(state["incident"], analysis, _documents(state))
        return {"enterpro_prompt": prompt}

    def create_git_branch(state: AgentState) -> dict[str, Any]:
        return {"branch_name": git.create_incident_branch(state["incident"])}

    def execute_enterpro(state: AgentState) -> dict[str, Any]:
        result = services.enterpro.execute(state["enterpro_prompt"], project_path)
        return {"enterpro_result": result}

    def validate_changes(state: AgentState) -> dict[str, Any]:
        files = git.changed_files()
        if not files:
            raise RuntimeError("Enter Pro completed without modifying any files")
        command = shlex.split(services.settings.validation_command, posix=False)
        try:
            completed = subprocess.run(
                command, cwd=project_path, text=True, capture_output=True,
                timeout=300, check=False,
            )
            validation = {
                "command": services.settings.validation_command,
                "passed": completed.returncode == 0,
                "exit_code": completed.returncode,
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-4000:],
                "tests_updated": any("test" in Path(name).name.lower() for name in files),
            }
        except (OSError, subprocess.TimeoutExpired) as exc:
            validation = {"command": services.settings.validation_command, "passed": False, "error": str(exc)}
        if not validation["passed"]:
            raise RuntimeError(f"Change validation failed: {validation}")
        return {"files_modified": files, "validation": validation}

    def update_decision_log(state: AgentState) -> dict[str, Any]:
        log_path = project_path / "docs" / "agent_decisions.md"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        references = state.get("memory_references") or ["No Parcle documentation found"]
        file_reasons = "\n".join(f"* `{name}` — changed by Enter Pro to implement or verify the remediation." for name in state["files_modified"])
        entry = f"""
## {_utc_now().strftime('%Y-%m-%d %H:%M UTC')}

**Incident:** {state['incident']}

**Documentation Referenced:**
{chr(10).join(f'* {reference}' for reference in references)}

**Hypothesis:** {state['root_cause_hypothesis']}

**Reasoning:** {state['hypothesis_reasoning']}

**Confidence:** {state['confidence_score']:.0%}

**Remediation Strategy:**
{chr(10).join(f'* {step}' for step in state['remediation_strategy'])}

**Files Modified:**
{file_reasons}

**Risks:** AI-generated changes may have repository-specific side effects; validation passed but human review is required.

**Follow-up Recommendations:** Review the diff and validation output, run staging checks, then push the branch manually if approved.

---
"""
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(entry)
        relative_log = log_path.relative_to(project_path).as_posix()
        return {
            "decision_log_path": relative_log,
            "decision_entry": entry,
            "documentation_updated": True,
            "files_modified": sorted(set([*state["files_modified"], relative_log])),
        }

    def sync_decision_to_parcle(state: AgentState) -> dict[str, Any]:
        document = ParcleMemoryDocument(
            id=f"employee-portal:incident:{state['run_id']}",
            title=f"Incident decision — {state['incident'][:120]}",
            content=state["decision_entry"],
            reference=state["decision_log_path"],
            metadata={
                "repository": "employee-portal",
                "content_type": "incident_decision",
                "run_id": state["run_id"],
                "branch_name": state["branch_name"],
                "confidence_score": state["confidence_score"],
                "recorded_at": _utc_now().isoformat(),
            },
        )
        return {"parcle_decision_sync": services.parcle.upsert_documents([document])}

    def commit_changes(state: AgentState) -> dict[str, Any]:
        summary = " ".join(state["incident"].split())[:72]
        commit_hash = git.commit_all(f"AI Incident Resolution: {summary}")
        return {"commit_hash": commit_hash}

    def return_summary(state: AgentState) -> dict[str, Any]:
        summary = (
            f"Resolved incident on local branch {state['branch_name']}; "
            f"validated and committed {len(state['files_modified'])} changed files. "
            "The branch was not pushed."
        )
        return {"summary": summary}

    return {
        "receive_incident": receive_incident,
        "search_parcle": search_parcle,
        "analyze_incident": analyze_incident,
        "generate_enterpro_prompt": generate_enterpro_prompt,
        "create_git_branch": create_git_branch,
        "execute_enterpro": execute_enterpro,
        "validate_changes": validate_changes,
        "update_decision_log": update_decision_log,
        "sync_decision_to_parcle": sync_decision_to_parcle,
        "commit_changes": commit_changes,
        "return_summary": return_summary,
    }
