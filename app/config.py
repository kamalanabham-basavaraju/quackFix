"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    groq_api_key: str | None
    groq_model: str
    parcle_base_url: str | None
    parcle_search_path: str
    parcle_upsert_path: str
    parcle_api_key: str | None
    parcle_namespace: str
    enterpro_url: str | None
    enterpro_api_key: str | None
    employee_portal_path: Path
    external_request_timeout: float
    validation_command: str
    enable_git_push: bool
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            groq_api_key=os.getenv("GROQ_API_KEY"),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            parcle_base_url=os.getenv("PARCLE_BASE_URL"),
            parcle_search_path=os.getenv("PARCLE_SEARCH_PATH", "/search"),
            parcle_upsert_path=os.getenv("PARCLE_UPSERT_PATH", "/documents/upsert"),
            parcle_api_key=os.getenv("PARCLE_API_KEY"),
            parcle_namespace=os.getenv("PARCLE_NAMESPACE", "employee-portal"),
            enterpro_url=os.getenv("ENTERPRO_URL") or os.getenv("ENTER_PRO_URL"),
            enterpro_api_key=os.getenv("ENTERPRO_API_KEY"),
            employee_portal_path=Path(os.getenv("EMPLOYEE_PORTAL_PATH", ".")).resolve(),
            external_request_timeout=float(os.getenv("EXTERNAL_REQUEST_TIMEOUT", "60")),
            validation_command=os.getenv("VALIDATION_COMMAND", "pytest -q"),
            enable_git_push=_as_bool(os.getenv("ENABLE_GIT_PUSH"), default=False),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )


settings = Settings.from_env()
