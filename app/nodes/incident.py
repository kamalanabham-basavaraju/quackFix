from __future__ import annotations

import logging
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from app.graph.state import AgentState
from app.integrations.git import GitClient
from app.models.incident import IncidentAnalysis, ParcleDocument, ParcleMemoryDocument, RequestClassification
from app.services.container import WorkflowServices

logger = logging.getLogger(__name__)
Node = Callable[[AgentState], dict[str, Any]]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _documents(state: AgentState) -> list[ParcleDocument]:
    return [ParcleDocument.model_validate(item) for item in state.get("parcle_documents", [])]


CODE_CHANGE_TERMS = {
    "fix",
    "change",
    "modify",
    "update",
    "implement",
    "add",
    "remove",
    "refactor",
    "bug",
    "error",
    "failing",
    "failure",
    "incident",
    "broken",
    "cannot",
    "can't",
    "not working",
    "test",
    "patch",
    "remediate",
    "resolve",
}

INFORMATION_PATTERNS = (
    r"\bwhat\s+is\b",
    r"\bwhat'?s\b",
    r"\bexplain\b",
    r"\bdescribe\b",
    r"\btell\s+me\b",
    r"\bhow\s+does\b",
    r"\boverview\b",
    r"\babout\b",
    r"\breadme\b",
)


def _requires_code_change(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    if any(term in normalized for term in CODE_CHANGE_TERMS):
        return True
    return not any(re.search(pattern, normalized) for pattern in INFORMATION_PATTERNS)


def _information_summary(state: AgentState) -> str:
    answer = state.get("information_answer", "").strip()
    if answer:
        return answer
    documents = _documents(state)
    if not documents:
        return (
            "This looks like an informational repo question, so I skipped code editing. "
            "Parcle did not return enough repository memory to answer it confidently."
        )
    answer = documents[0].content.strip()
    if not answer:
        answer = "Parcle returned a matching memory item, but it did not include answer text."
    references = [document.reference for document in documents if document.reference]
    suffix = f" References: {', '.join(references)}." if references else ""
    return f"{answer}{suffix}"


def _markdown_parcle_documents(documents: list[ParcleDocument]) -> str:
    if not documents:
        return "No Parcle documents were returned."
    lines: list[str] = []
    for index, document in enumerate(documents, start=1):
        excerpt = document.content.strip()
        if len(excerpt) > 3000:
            excerpt = excerpt[:3000] + "\n...[truncated]"
        lines.extend(
            [
                f"### Result {index}: {document.title}",
                f"- Reference: {document.reference or 'none'}",
                f"- Metadata: `{document.metadata}`",
                "",
                excerpt,
                "",
            ]
        )
    return "\n".join(lines).strip()


def _enterpro_execution_prompt(prompt: str, project_path: Path, memory_dir: str = "docs/parcle_memory") -> str:
    return f"""{prompt}

Execution Context:
- You are running from the target local Git repository at `{project_path}`.
- Inspect the current working tree before editing.
- Apply the remediation directly to files in this local repository. Do not only explain a plan.
- Add or update regression tests when the repository has a test structure.
- Update relevant project documentation when behavior changes.
- Do not push, publish, deploy, or open a pull request.
- Before finishing, run `git status --short` and ensure at least one file is modified in this working tree.
- If you believe no code change is safe, still write a short investigation note under `{memory_dir}/incidents/` explaining why no automated code change was made.
"""


def _enterpro_failure_context(state: AgentState) -> dict[str, Any]:
    result = state.get("enterpro_result") or {}
    return {
        "command": result.get("command"),
        "exit_code": result.get("exit_code"),
        "stdout": str(result.get("stdout", ""))[-4000:],
        "stderr": str(result.get("stderr", ""))[-4000:],
        "json": result.get("json"),
    }


def _validation_repair_prompt(state: AgentState, project_path: Path) -> str:
    validation = state.get("validation", {})
    return f"""The previous automated code edit for this incident failed validation.

Incident:
{state['incident']}

Target repository:
{project_path}

Validation command:
{validation.get('command')}

Exit code:
{validation.get('exit_code')}

Stdout:
{validation.get('stdout', '')}

Stderr:
{validation.get('stderr', '')}

Fix the validation failure directly in the local repository. Prefer using the project's existing dependency stack and
test patterns. If a new dependency is truly required, update the appropriate dependency manifest in the repository.
Do not add tests that require unconfigured packages such as SQLAlchemy, pydantic[email], or email-validator unless
the repository already depends on them or you also update the dependency manifest. Run `git status --short` before
finishing and leave the working tree with the corrected files modified.
"""


def build_nodes(services: WorkflowServices) -> dict[str, Node]:
    project_path = services.settings.employee_portal_path
    memory_dir = project_path / services.settings.parcle_memory_dir
    git = GitClient(project_path, require_clean=services.settings.require_clean_target_repo)

    def receive_incident(state: AgentState) -> dict[str, Any]:
        incident = state.get("incident", "").strip()
        if not incident:
            raise ValueError("incident must not be empty")
        logger.info("Incident run started", extra={"incident_run_id": state.get("run_id")})
        next_state = {
            "incident": incident,
            "run_id": state.get("run_id") or str(uuid4()),
            "started_at": state.get("started_at") or _utc_now().isoformat(),
            "project_path": str(project_path),
            "errors": [],
        }
        if state.get("parcle_query"):
            next_state["parcle_query"] = state["parcle_query"]
        if state.get("produck_ticket_id"):
            next_state["produck_ticket_id"] = state["produck_ticket_id"]
            next_state["produck_payload"] = state.get("produck_payload", {})
            next_state["produck_brief"] = state.get("produck_brief", "")
        return next_state

    def search_parcle(state: AgentState) -> dict[str, Any]:
        query = state.get("parcle_query") or state["incident"]
        documents = services.parcle.search(query)
        logger.info(
            "Parcle memory retrieved",
            extra={
                "incident_run_id": state.get("run_id"),
                "query_chars": len(query),
                "document_count": len(documents),
                "references": [document.reference for document in documents if document.reference],
            },
        )
        return {
            "parcle_documents": [document.model_dump(mode="json") for document in documents],
            "memory_references": [document.reference for document in documents if document.reference],
            "parcle_query": query,
        }

    def classify_request(state: AgentState) -> dict[str, Any]:
        classifier = getattr(services.groq, "classify_request", None)
        if callable(classifier):
            classification = classifier(state["incident"], _documents(state))
            classification = RequestClassification.model_validate(classification)
            return {
                "request_kind": classification.request_kind,
                "classification_reasoning": classification.reasoning,
                "information_answer": classification.answer,
            }
        request_kind = "code_change" if _requires_code_change(state["incident"]) else "information"
        return {
            "request_kind": request_kind,
            "classification_reasoning": "Fallback heuristic classifier used.",
            "information_answer": "",
        }

    def return_information(state: AgentState) -> dict[str, Any]:
        return {
            "branch_name": "",
            "files_modified": [],
            "documentation_updated": False,
            "commit_hash": "",
            "summary": _information_summary(state),
            "validation": {
                "skipped": True,
                "reason": "informational_request",
                "classification_reasoning": state.get("classification_reasoning", ""),
                "memory_references": state.get("memory_references", []),
            },
        }

    def analyze_incident(state: AgentState) -> dict[str, Any]:
        analysis = services.groq.analyze(state["incident"], _documents(state))
        return analysis.model_dump()

    def generate_enterpro_prompt(state: AgentState) -> dict[str, Any]:
        analysis = IncidentAnalysis.model_validate(state)
        prompt = services.groq.generate_enterpro_prompt(state["incident"], analysis, _documents(state))
        logger.info(
            "Enter Pro prompt generated",
            extra={"incident_run_id": state.get("run_id"), "prompt_chars": len(prompt)},
        )
        return {"enterpro_prompt": prompt}

    def preflight_git_push(state: AgentState) -> dict[str, Any]:
        if not services.settings.enable_git_push:
            return {"git_preflight": {"skipped": True, "reason": "ENABLE_GIT_PUSH is false"}}
        if not services.settings.github_token:
            raise RuntimeError("GITHUB_TOKEN or GH_TOKEN is required before running an automated code-change flow")
        git.assert_push_access(services.settings.github_token, services.settings.github_api_url)
        return {"git_preflight": {"skipped": False, "result": "push access verified"}}

    def create_git_branch(state: AgentState) -> dict[str, Any]:
        branch_source = state.get("root_cause_hypothesis") or state["incident"]
        return {
            "branch_name": git.create_incident_branch(
                state["incident"], branch_source, services.settings.github_base_branch
            )
        }

    def execute_enterpro(state: AgentState) -> dict[str, Any]:
        prompt = _enterpro_execution_prompt(
            state["enterpro_prompt"], project_path, services.settings.parcle_memory_dir
        )
        result = services.enterpro.execute(prompt, project_path)
        return {"enterpro_result": result}

    def validate_changes(state: AgentState) -> dict[str, Any]:
        files = git.changed_files()
        if not files:
            raise RuntimeError(
                f"Enter Pro completed without modifying any files: {_enterpro_failure_context(state)}"
            )
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
            if completed.returncode == 5 and "no tests ran" in completed.stdout.lower():
                validation["passed"] = True
                validation["warning"] = "Validation command ran successfully but found no tests."
        except (OSError, subprocess.TimeoutExpired) as exc:
            validation = {"command": services.settings.validation_command, "passed": False, "error": str(exc)}
        if not validation["passed"]:
            return {"files_modified": files, "validation": validation}
        return {"files_modified": files, "validation": validation}

    def repair_validation(state: AgentState) -> dict[str, Any]:
        validation = state.get("validation", {})
        if validation.get("passed"):
            return {}
        repair_prompt = _validation_repair_prompt(state, project_path)
        repair_result = services.enterpro.execute(repair_prompt, project_path)
        files = git.changed_files()
        command = shlex.split(services.settings.validation_command, posix=False)
        try:
            completed = subprocess.run(
                command, cwd=project_path, text=True, capture_output=True,
                timeout=300, check=False,
            )
            repaired_validation = {
                "command": services.settings.validation_command,
                "passed": completed.returncode == 0,
                "exit_code": completed.returncode,
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-4000:],
                "tests_updated": any("test" in Path(name).name.lower() for name in files),
                "repair_attempted": True,
            }
            if completed.returncode == 5 and "no tests ran" in completed.stdout.lower():
                repaired_validation["passed"] = True
                repaired_validation["warning"] = "Validation command ran successfully but found no tests."
        except (OSError, subprocess.TimeoutExpired) as exc:
            repaired_validation = {
                "command": services.settings.validation_command,
                "passed": False,
                "error": str(exc),
                "repair_attempted": True,
            }
        if not repaired_validation["passed"]:
            raise RuntimeError(
                f"Change validation failed after one repair attempt: {repaired_validation}"
            )
        return {
            "files_modified": files,
            "validation": repaired_validation,
            "enterpro_repair_result": repair_result,
        }

    def update_decision_log(state: AgentState) -> dict[str, Any]:
        log_path = memory_dir / "agent_decisions.md"
        incident_dir = memory_dir / "incidents"
        incident_path = incident_dir / f"{state['started_at'][:10]}-{state['run_id']}.md"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        incident_dir.mkdir(parents=True, exist_ok=True)
        references = state.get("memory_references") or ["No Parcle documentation found"]
        parcle_query = state.get("parcle_query") or state["incident"]
        parcle_retrieval = _markdown_parcle_documents(_documents(state))
        enter_prompt = state.get("enterpro_prompt", "")
        produck_section = ""
        if state.get("produck_ticket_id"):
            produck_section = f"""
## Produck Source

**Ticket ID:** {state.get('produck_ticket_id')}

### Brief
{state.get('produck_brief', '')}
"""
        file_reasons = "\n".join(f"* `{name}` - changed by Enter Pro to implement or verify the remediation." for name in state["files_modified"])
        challenges = []
        validation = state.get("validation", {})
        if validation.get("warning"):
            challenges.append(str(validation["warning"]))
        enter_result = state.get("enterpro_result", {})
        if enter_result.get("stderr"):
            challenges.append(str(enter_result["stderr"])[-1000:])
        challenges_text = "\n".join(f"* {challenge}" for challenge in challenges) or "* None recorded."
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

**Parcle Query:** Captured in `{incident_path.relative_to(project_path).as_posix()}`.

**Parcle Retrieval:** Captured in `{incident_path.relative_to(project_path).as_posix()}`.

**Enter Pro Prompt:** Captured in `{incident_path.relative_to(project_path).as_posix()}`.

**Challenges:**
{challenges_text}

**Risks:** AI-generated changes may have repository-specific side effects; validation passed but human review is required.

**Follow-up Recommendations:** Review the diff and validation output, run staging checks, then push the branch manually if approved.

---
"""
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(entry)
        incident_path.write_text(
            f"""# Incident Record

**Run ID:** {state['run_id']}
**Branch:** {state['branch_name']}
**Incident:** {state['incident']}
**Recorded At:** {_utc_now().isoformat()}

## Files Fixed
{file_reasons}

## Fix Summary
{state['root_cause_hypothesis']}

## Reasoning
{state['hypothesis_reasoning']}

{produck_section}

## Parcle Query
```text
{parcle_query}
```

## Parcle Retrieval
{parcle_retrieval}

## Enter Pro Prompt
```text
{enter_prompt}
```

## Enter Pro Result
```json
{enter_result}
```

## Validation
```json
{validation}
```

## Challenges
{challenges_text}

## Parcle References
{chr(10).join(f'* {reference}' for reference in references)}
""",
            encoding="utf-8",
        )
        relative_log = log_path.relative_to(project_path).as_posix()
        relative_incident = incident_path.relative_to(project_path).as_posix()
        return {
            "decision_log_path": relative_log,
            "incident_record_path": relative_incident,
            "decision_entry": entry,
            "documentation_updated": True,
            "files_modified": sorted(set([*state["files_modified"], relative_log, relative_incident])),
        }

    def sync_decision_to_parcle(state: AgentState) -> dict[str, Any]:
        incident_file = project_path / state["incident_record_path"]
        result = services.parcle.ingest_files([incident_file])
        document = ParcleMemoryDocument(
            id=f"employee-portal:incident:{state['run_id']}",
            title=f"Incident decision - {state['incident'][:120]}",
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
        dialog_result = services.parcle.ingest_documents([document])
        return {"parcle_decision_sync": {"file": result, "dialog": dialog_result}}

    def commit_changes(state: AgentState) -> dict[str, Any]:
        summary = " ".join((state.get("root_cause_hypothesis") or state["incident"]).split())[:72]
        subprocess.run(["git", "config", "--local", "user.email", "agent@langgraph.local"], cwd=project_path)
        subprocess.run(["git", "config", "--local", "user.name", "LangGraph Agent"], cwd=project_path)
        commit_hash = git.commit_all(f"AI Incident Resolution: {summary}")
        return {"commit_hash": commit_hash}

    def push_branch(state: AgentState) -> dict[str, Any]:
        if not services.settings.enable_git_push:
            return {"pull_request_url": None, "push": {"skipped": True, "reason": "ENABLE_GIT_PUSH is false"}}
        if not services.settings.github_token:
            raise RuntimeError("GITHUB_TOKEN or GH_TOKEN is required to push branches")
        git.push_branch(state["branch_name"], services.settings.github_token)
        return {"push": {"skipped": False, "branch_name": state["branch_name"]}}

    def create_pull_request(state: AgentState) -> dict[str, Any]:
        if not services.settings.enable_git_push:
            return {"pull_request_url": None}
        if not services.settings.github_token:
            raise RuntimeError("GITHUB_TOKEN or GH_TOKEN is required to create pull requests")
        title_source = state.get("root_cause_hypothesis") or state["incident"]
        title = f"AI Incident Resolution: {title_source[:90]}"
        body = f"""## Incident
{state['incident']}

## Change Brief
{state.get('root_cause_hypothesis', 'No hypothesis recorded.')}

## Reasoning
{state.get('hypothesis_reasoning', 'No reasoning recorded.')}

## Remediation Strategy
{chr(10).join(f'* {step}' for step in state.get('remediation_strategy', [])) or '* No remediation strategy recorded.'}

## Files Modified
{chr(10).join(f'* `{name}`' for name in state['files_modified'])}

## Parcle Evidence
Query:
```text
{state.get('parcle_query') or state['incident']}
```

References:
{chr(10).join(f'* {reference}' for reference in state.get('memory_references', [])) or '* No Parcle references returned.'}

## Incident Record
`{state['incident_record_path']}`

## Validation
{state['validation']}
"""
        pr = git.create_pull_request(
            services.settings.github_token,
            state["branch_name"],
            services.settings.github_base_branch,
            title,
            body,
            services.settings.github_api_url,
        )
        return {"pull_request_url": pr.get("html_url") or pr.get("url")}

    def return_summary(state: AgentState) -> dict[str, Any]:
        summary = (
            f"Resolved incident on local branch {state['branch_name']}; "
            f"validated and committed {len(state['files_modified'])} changed files. "
            f"Pull request: {state.get('pull_request_url') or 'not created'}."
        )
        return {"summary": summary}

    return {
        "receive_incident": receive_incident,
        "search_parcle": search_parcle,
        "classify_request": classify_request,
        "return_information": return_information,
        "analyze_incident": analyze_incident,
        "generate_enterpro_prompt": generate_enterpro_prompt,
        "preflight_git_push": preflight_git_push,
        "create_git_branch": create_git_branch,
        "execute_enterpro": execute_enterpro,
        "validate_changes": validate_changes,
        "repair_validation": repair_validation,
        "update_decision_log": update_decision_log,
        "sync_decision_to_parcle": sync_decision_to_parcle,
        "commit_changes": commit_changes,
        "push_branch": push_branch,
        "create_pull_request": create_pull_request,
        "return_summary": return_summary,
    }
