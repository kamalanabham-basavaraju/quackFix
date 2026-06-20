from __future__ import annotations

import subprocess
from pathlib import Path

from app.config import Settings
from app.graph.workflow import NODE_ORDER, create_graph
from app.models.incident import IncidentAnalysis, ParcleDocument
from app.services.container import WorkflowServices


class FakeParcle:
    def search(self, query: str, limit: int = 8) -> list[ParcleDocument]:
        assert "profile" in query
        return [ParcleDocument(title="Profile API", content="Validation changed", reference="docs/profile.md")]

    def upsert_documents(self, documents):
        assert documents[0].metadata["content_type"] == "incident_decision"
        return {"location": "test-memory", "documents_submitted": len(documents)}


class FakeGroq:
    def analyze(self, incident: str, documents: list[ParcleDocument]) -> IncidentAnalysis:
        return IncidentAnalysis(
            root_cause_hypothesis="Profile validation mismatch",
            affected_components=["profile-api"],
            confidence_score=0.8,
            remediation_strategy=["Align validation rules"],
            hypothesis_reasoning="The documentation records a validation change.",
            files_likely_affected=["profile.py"],
        )

    def generate_enterpro_prompt(self, incident, analysis, documents) -> str:
        return "Implement the profile validation fix, tests, and documentation. Do not push."


class FakeEnterPro:
    def execute(self, prompt: str, project_path: Path) -> dict[str, object]:
        (project_path / "profile.py").write_text("VALIDATION_FIXED = True\n", encoding="utf-8")
        tests = project_path / "tests"
        tests.mkdir(exist_ok=True)
        (tests / "test_profile.py").write_text("def test_profile():\n    assert True\n", encoding="utf-8")
        return {"status": "completed"}


def _run(path: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=path, check=True, text=True, capture_output=True).stdout.strip()


def test_complete_graph_creates_local_branch_and_commit(tmp_path: Path):
    _run(tmp_path, "init")
    _run(tmp_path, "config", "user.email", "test@example.com")
    _run(tmp_path, "config", "user.name", "Test User")
    (tmp_path / "README.md").write_text("portal\n", encoding="utf-8")
    _run(tmp_path, "add", ".")
    _run(tmp_path, "commit", "-m", "baseline")

    config = Settings(
        groq_api_key=None,
        groq_model="test",
        parcle_base_url=None,
        parcle_search_path="/search",
        parcle_upsert_path="/documents/upsert",
        parcle_api_key=None,
        parcle_namespace="employee-portal",
        enterpro_url=None,
        enterpro_api_key=None,
        employee_portal_path=tmp_path,
        external_request_timeout=1,
        validation_command="git status --short",
        enable_git_push=False,
        log_level="INFO",
    )
    services = WorkflowServices(FakeParcle(), FakeGroq(), FakeEnterPro(), config)  # type: ignore[arg-type]

    result = create_graph(services).invoke({"incident": "Users cannot update profile"})

    assert result["branch_name"].startswith("incident/")
    assert result["commit_hash"] == _run(tmp_path, "rev-parse", "HEAD")
    assert result["documentation_updated"] is True
    assert "docs/agent_decisions.md" in result["files_modified"]
    assert result["validation"]["passed"] is True
    assert "not pushed" in result["summary"]
    assert _run(tmp_path, "remote") == ""


def test_workflow_has_all_required_nodes():
    assert NODE_ORDER == [
        "receive_incident", "search_parcle", "analyze_incident", "generate_enterpro_prompt",
        "create_git_branch", "execute_enterpro", "validate_changes", "update_decision_log",
        "sync_decision_to_parcle", "commit_changes", "return_summary",
    ]
