"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_memory_path(value: str | None, project_path: Path, memory_dir: str, default_name: str) -> Path:
    raw = (value or default_name).strip()
    path = Path(raw)
    if path.is_absolute():
        return path.resolve()
    return (project_path / memory_dir / path).resolve()


def _resolve_runtime_path(value: str | None, default_name: str) -> Path:
    raw = (value or default_name).strip()
    path = Path(raw)
    if path.is_absolute():
        return path.resolve()
    return (Path.home() / ".langgraph-starter" / path).resolve()


@dataclass(frozen=True)
class Settings:
    groq_api_key: str | None
    groq_model: str
    parcle_api_key: str | None
    parcle_user_id: str
    enterpro_url: str | None
    enterpro_api_key: str | None
    enterpro_command: str | None
    enterpro_workspace_id: str | None
    employee_portal_path: Path
    parcle_memory_dir: str
    external_request_timeout: float
    validation_command: str
    require_clean_target_repo: bool
    enable_git_push: bool
    github_token: str | None
    github_base_branch: str
    github_api_url: str
    produck_mcp_url: str = "https://tryproduck.com/api/mcp"
    produck_mcp_token: str | None = None
    produck_poll_enabled: bool = False
    produck_poll_interval_seconds: int = 120
    produck_max_tickets_per_poll: int = 1
    produck_feedback_ids: tuple[str, ...] = ()
    produck_search_domain: str | None = None
    produck_state_path: Path = Path(".state/produck_ticket_state.json")
    produck_legacy_state_path: Path | None = None
    produck_output_dir: Path = Path("produck_out")
    produck_close_on_success: bool = False
    produck_mcp_timeout: float = 60
    log_level: str = "INFO"

    def with_employee_portal_path(self, value: str | None) -> "Settings":
        if not value:
            return self
        employee_portal_path = Path(value).expanduser().resolve()
        return replace(
            self,
            employee_portal_path=employee_portal_path,
            produck_legacy_state_path=(
                employee_portal_path / self.parcle_memory_dir / ".state/produck_ticket_state.json"
            ).resolve(),
            produck_output_dir=_resolve_memory_path(
                os.getenv("PRODUCK_OUTPUT_DIR"),
                employee_portal_path,
                self.parcle_memory_dir,
                "produck_tickets",
            ),
        )

    @classmethod
    def from_env(cls) -> "Settings":
        employee_portal_path = Path(os.getenv("EMPLOYEE_PORTAL_PATH", ".")).resolve()
        parcle_memory_dir = os.getenv("PARCLE_MEMORY_DIR", "docs/parcle_memory")
        return cls(
            groq_api_key=os.getenv("GROQ_API_KEY"),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            parcle_api_key=os.getenv("PARCLE_API_KEY"),
            parcle_user_id=os.getenv("PARCLE_USER_ID", "system_user"),
            enterpro_url=os.getenv("ENTERPRO_URL") or os.getenv("ENTER_PRO_URL"),
            enterpro_api_key=os.getenv("ENTERPRO_API_KEY"),
            enterpro_command=os.getenv("ENTERPRO_COMMAND"),
            enterpro_workspace_id=os.getenv("ENTERPRO_WORKSPACE_ID"),
            employee_portal_path=employee_portal_path,
            parcle_memory_dir=parcle_memory_dir,
            external_request_timeout=float(os.getenv("EXTERNAL_REQUEST_TIMEOUT", "60")),
            validation_command=os.getenv("VALIDATION_COMMAND", "pytest -q"),
            require_clean_target_repo=_as_bool(os.getenv("REQUIRE_CLEAN_TARGET_REPO"), default=False),
            enable_git_push=_as_bool(os.getenv("ENABLE_GIT_PUSH"), default=False),
            github_token=os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN"),
            github_base_branch=os.getenv("GITHUB_BASE_BRANCH", "main"),
            github_api_url=os.getenv("GITHUB_API_URL", "https://api.github.com"),
            produck_mcp_url=os.getenv("PRODUCK_MCP_URL", "https://tryproduck.com/api/mcp"),
            produck_mcp_token=os.getenv("PRODUCK_MCP_TOKEN"),
            produck_poll_enabled=_as_bool(os.getenv("PRODUCK_POLL_ENABLED"), default=False),
            produck_poll_interval_seconds=int(os.getenv("PRODUCK_POLL_INTERVAL_SECONDS", "120")),
            produck_max_tickets_per_poll=int(os.getenv("PRODUCK_MAX_TICKETS_PER_POLL", "1")),
            produck_feedback_ids=tuple(
                item.strip() for item in os.getenv("PRODUCK_FEEDBACK_IDS", "").split(",") if item.strip()
            ),
            produck_search_domain=os.getenv("PRODUCK_SEARCH_DOMAIN") or None,
            produck_state_path=_resolve_runtime_path(
                os.getenv("PRODUCK_STATE_PATH"),
                "produck_ticket_state.json",
            ),
            produck_legacy_state_path=(
                employee_portal_path / parcle_memory_dir / ".state/produck_ticket_state.json"
            ).resolve(),
            produck_output_dir=_resolve_memory_path(
                os.getenv("PRODUCK_OUTPUT_DIR"),
                employee_portal_path,
                parcle_memory_dir,
                "produck_tickets",
            ),
            produck_close_on_success=_as_bool(os.getenv("PRODUCK_CLOSE_ON_SUCCESS"), default=False),
            produck_mcp_timeout=float(os.getenv("PRODUCK_MCP_TIMEOUT", "60")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )


settings = Settings.from_env()
