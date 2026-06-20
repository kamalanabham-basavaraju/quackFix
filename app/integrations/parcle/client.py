from __future__ import annotations

import logging
from typing import Any

import requests

from app.models.incident import ParcleDocument, ParcleMemoryDocument

logger = logging.getLogger(__name__)


class ParcleError(RuntimeError):
    """Raised when a Parcle memory operation fails."""


class ParcleClient:
    def __init__(
        self,
        base_url: str | None,
        search_path: str,
        upsert_path: str,
        api_key: str | None,
        namespace: str,
        timeout: float,
    ):
        self.base_url = base_url
        self.search_path = search_path
        self.upsert_path = upsert_path
        self.api_key = api_key
        self.namespace = namespace
        self.timeout = timeout

    @property
    def memory_location(self) -> str:
        if not self.base_url:
            return f"unconfigured namespace:{self.namespace}"
        return f"{self.base_url.rstrip('/')} namespace:{self.namespace}"

    def _url(self, path: str) -> str:
        if not self.base_url:
            raise ParcleError("PARCLE_BASE_URL is not configured")
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _post(self, path: str, payload: dict[str, Any], operation: str) -> Any:
        url = self._url(path)
        try:
            response = requests.post(
                url, json=payload, headers=self._headers(), timeout=self.timeout
            )
            response.raise_for_status()
            return response.json() if response.content else {}
        except (requests.RequestException, ValueError) as exc:
            logger.exception("Parcle operation failed", extra={"url": url, "operation": operation})
            raise ParcleError(f"Parcle {operation} failed: {exc}") from exc

    def search(self, query: str, limit: int = 8) -> list[ParcleDocument]:
        payload = self._post(
            self.search_path,
            {"query": query, "limit": limit, "namespace": self.namespace},
            "search",
        )
        raw_documents = payload.get("documents", payload.get("results", [])) if isinstance(payload, dict) else payload
        if not isinstance(raw_documents, list):
            raise ParcleError("Parcle returned an unsupported search response shape")
        return [self._normalize(item) for item in raw_documents if isinstance(item, dict)]

    def upsert_documents(self, documents: list[ParcleMemoryDocument]) -> dict[str, Any]:
        if not documents:
            raise ParcleError("At least one document is required for Parcle ingestion")
        payload = self._post(
            self.upsert_path,
            {
                "namespace": self.namespace,
                "documents": [document.model_dump(mode="json") for document in documents],
            },
            "document upsert",
        )
        return {
            "location": self.memory_location,
            "namespace": self.namespace,
            "documents_submitted": len(documents),
            "response": payload,
        }

    @staticmethod
    def _normalize(item: dict[str, Any]) -> ParcleDocument:
        return ParcleDocument(
            title=str(item.get("title") or item.get("name") or "Untitled"),
            content=str(item.get("content") or item.get("text") or item.get("snippet") or ""),
            reference=item.get("reference") or item.get("url") or item.get("id"),
            metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
        )
