from __future__ import annotations

import subprocess
from pathlib import Path

from app.config import Settings
from app.graph.workflow import CODE_CHANGE_ORDER, NODE_ORDER, create_graph
from app.models.incident import IncidentAnalysis, ParcleDocument, RequestClassification
from app.nodes.incident import _enterpro_execution_prompt
from app.services.container import WorkflowServices


class FakeParcle:
    def __init__(self):
        self.queries = []

    def search(self, query: str, limit: int = 8) -> list[ParcleDocument]:
        self.queries.append(query)
        return [ParcleDocument(title="Profile API", content="Validation changed", reference="docs/profile.md")]

    def ingest_documents(self, documents):
        assert documents[0].metadata["content_type"] == "incident_decision"
        return {"location": "test-memory", "documents_submitted": len(documents)}

    def ingest_files(self, files):
        return {"location": "test-memory", "files_submitted": len(files)}


class FakeGroq:
    def classify_request(self, request: str, documents: list[ParcleDocument]) -> RequestClassification:
        if request.lower().startswith("what is"):
            return RequestClassification(
                request_kind="information",
                reasoning="The user asked a read-only repo question.",
                answer="This repository contains an Employee Tracker service.",
            )
        return RequestClassification(
            request_kind="code_change",
            reasoning="The user described a behavior that needs remediation.",
        )

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


class FailingEnterPro:
    def execute(self, prompt: str, project_path: Path) -> dict[str, object]:
        raise AssertionError("Enter Pro should not be called for informational requests")


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
        parcle_api_key=None,
        parcle_user_id="system_user",
        enterpro_url=None,
        enterpro_api_key=None,
        enterpro_command=None,
        enterpro_workspace_id=None,
        employee_portal_path=tmp_path,
        parcle_memory_dir="docs/parcle_memory",
        external_request_timeout=1,
        validation_command="git status --short",
        require_clean_target_repo=False,
        enable_git_push=False,
        github_token=None,
        github_base_branch="main",
        github_api_url="https://api.github.com",
        log_level="INFO",
    )
    parcle = FakeParcle()
    services = WorkflowServices(parcle, FakeGroq(), FakeEnterPro(), config)  # type: ignore[arg-type]

    result = create_graph(services).invoke({"incident": "Users cannot update profile"})

    assert result["branch_name"].startswith("ai/")
    assert result["commit_hash"] == _run(tmp_path, "rev-parse", "HEAD")
    assert result["documentation_updated"] is True
    assert "docs/parcle_memory/agent_decisions.md" in result["files_modified"]
    assert result["incident_record_path"].startswith("docs/parcle_memory/incidents/")
    assert result["validation"]["passed"] is True
    assert "Pull request: not created" in result["summary"]
    assert _run(tmp_path, "remote") == ""
    assert parcle.queries == ["Users cannot update profile"]


def test_workflow_has_all_required_nodes():
    assert NODE_ORDER == [
        "receive_incident", "search_parcle", "classify_request", "return_information",
        "analyze_incident", "generate_enterpro_prompt",
        "preflight_git_push",
        "create_git_branch", "execute_enterpro", "validate_changes", "repair_validation", "update_decision_log",
        "sync_decision_to_parcle", "commit_changes", "push_branch", "create_pull_request",
        "return_summary",
    ]
    assert CODE_CHANGE_ORDER == [
        "analyze_incident", "generate_enterpro_prompt", "preflight_git_push", "create_git_branch", "execute_enterpro",
        "validate_changes", "repair_validation", "update_decision_log", "sync_decision_to_parcle", "commit_changes",
        "push_branch", "create_pull_request", "return_summary",
    ]


def test_enterpro_prompt_requires_local_working_tree_changes(tmp_path: Path):
    prompt = _enterpro_execution_prompt("Fix the profile validation bug.", tmp_path)

    assert str(tmp_path) in prompt
    assert "Apply the remediation directly to files" in prompt
    assert "git status --short" in prompt


def test_informational_request_skips_enter_and_git(tmp_path: Path):
    config = Settings(
        groq_api_key=None,
        groq_model="test",
        parcle_api_key=None,
        parcle_user_id="system_user",
        enterpro_url=None,
        enterpro_api_key=None,
        enterpro_command=None,
        enterpro_workspace_id=None,
        employee_portal_path=tmp_path,
        parcle_memory_dir="docs/parcle_memory",
        external_request_timeout=1,
        validation_command="git status --short",
        require_clean_target_repo=True,
        enable_git_push=False,
        github_token=None,
        github_base_branch="main",
        github_api_url="https://api.github.com",
        log_level="INFO",
    )
    services = WorkflowServices(FakeParcle(), FakeGroq(), FailingEnterPro(), config)  # type: ignore[arg-type]

    result = create_graph(services).invoke({"incident": "What is this repo about?"})

    assert result["branch_name"] == ""
    assert result["commit_hash"] == ""
    assert result["files_modified"] == []
    assert result["documentation_updated"] is False
    assert result["validation"]["reason"] == "informational_request"
    assert result["validation"]["classification_reasoning"] == "The user asked a read-only repo question."
    assert "Employee Tracker service" in result["summary"]


def test_graph_uses_explicit_parcle_query(tmp_path: Path):
    config = Settings(
        groq_api_key=None,
        groq_model="test",
        parcle_api_key=None,
        parcle_user_id="system_user",
        enterpro_url=None,
        enterpro_api_key=None,
        enterpro_command=None,
        enterpro_workspace_id=None,
        employee_portal_path=tmp_path,
        parcle_memory_dir="docs/parcle_memory",
        external_request_timeout=1,
        validation_command="git status --short",
        require_clean_target_repo=True,
        enable_git_push=False,
        github_token=None,
        github_base_branch="main",
        github_api_url="https://api.github.com",
        log_level="INFO",
    )
    parcle = FakeParcle()
    services = WorkflowServices(parcle, FakeGroq(), FailingEnterPro(), config)  # type: ignore[arg-type]

    create_graph(services).invoke(
        {
            "incident": "What is this repo about?",
            "parcle_query": "route /app/mcp color feedback anchor x 1209 y 697",
        }
    )

    assert parcle.queries == ["route /app/mcp color feedback anchor x 1209 y 697"]
