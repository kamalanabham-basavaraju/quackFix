from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.integrations.parcle import ParcleClient
from app.models.incident import ParcleMemoryDocument

EMPLOYEE_PORTAL_MEMORY_FILES = (
    "API_DOCUMENTATION.md",
    "PARCLE_MEMORY.md",
    "README.md",
)


class ParcleIngestionService:
    def __init__(self, client: ParcleClient, project_path: Path):
        self.client = client
        self.project_path = project_path.resolve()

    def load_documents(self) -> list[ParcleMemoryDocument]:
        missing = [name for name in EMPLOYEE_PORTAL_MEMORY_FILES if not (self.project_path / name).is_file()]
        if missing:
            raise FileNotFoundError(
                f"Missing required Employee Portal memory files in {self.project_path}: {', '.join(missing)}"
            )

        documents: list[ParcleMemoryDocument] = []
        for filename in EMPLOYEE_PORTAL_MEMORY_FILES:
            path = self.project_path / filename
            content = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
            documents.append(
                ParcleMemoryDocument(
                    id=f"employee-portal:{filename.lower()}",
                    title=f"Employee Portal — {filename}",
                    content=content,
                    reference=filename,
                    metadata={
                        "repository": "employee-portal",
                        "source_path": filename,
                        "content_type": "project_documentation",
                        "sha256": checksum,
                        "indexed_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            )
        return documents

    def ingest(self, dry_run: bool = False) -> dict[str, Any]:
        documents = self.load_documents()
        if dry_run:
            return {
                "dry_run": True,
                "location": self.client.memory_location,
                "documents_submitted": 0,
                "documents_found": [document.reference for document in documents],
            }
        result = self.client.upsert_documents(documents)
        result["documents_found"] = [document.reference for document in documents]
        return result
