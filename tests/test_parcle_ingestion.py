from pathlib import Path

import pytest

from app.services.parcle_ingestion import EMPLOYEE_PORTAL_MEMORY_FILES, ParcleIngestionService


class RecordingParcle:
    memory_location = "https://parcle.example/api namespace:employee-portal"

    def __init__(self):
        self.documents = []

    def upsert_documents(self, documents):
        self.documents = documents
        return {"location": self.memory_location, "documents_submitted": len(documents)}


def test_ingests_exact_employee_portal_memory_files(tmp_path: Path):
    for name in EMPLOYEE_PORTAL_MEMORY_FILES:
        (tmp_path / name).write_text(f"# {name}\ncontent", encoding="utf-8")
    parcle = RecordingParcle()

    result = ParcleIngestionService(parcle, tmp_path).ingest()  # type: ignore[arg-type]

    assert result["documents_submitted"] == 3
    assert [document.reference for document in parcle.documents] == list(EMPLOYEE_PORTAL_MEMORY_FILES)
    assert parcle.documents[0].id == "employee-portal:api_documentation.md"
    assert len(parcle.documents[0].metadata["sha256"]) == 64


def test_ingestion_reports_all_missing_required_files(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="API_DOCUMENTATION.md.*PARCLE_MEMORY.md.*README.md"):
        ParcleIngestionService(RecordingParcle(), tmp_path).load_documents()  # type: ignore[arg-type]


def test_dry_run_does_not_write_to_parcle(tmp_path: Path):
    for name in EMPLOYEE_PORTAL_MEMORY_FILES:
        (tmp_path / name).write_text("content", encoding="utf-8")
    parcle = RecordingParcle()

    result = ParcleIngestionService(parcle, tmp_path).ingest(dry_run=True)  # type: ignore[arg-type]

    assert result["dry_run"] is True
    assert result["documents_submitted"] == 0
    assert parcle.documents == []
