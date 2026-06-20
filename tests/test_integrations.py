from app.integrations.parcle.client import ParcleClient
from app.models.incident import ParcleMemoryDocument


def test_parcle_normalizes_common_response_fields():
    document = ParcleClient._normalize(
        {"name": "Runbook", "snippet": "Restart the worker", "url": "docs/runbook", "metadata": {"team": "ops"}}
    )
    assert document.title == "Runbook"
    assert document.content == "Restart the worker"
    assert document.reference == "docs/runbook"
    assert document.metadata == {"team": "ops"}


def test_parcle_upsert_uses_configured_namespace(monkeypatch):
    client = ParcleClient(
        "https://parcle.example/api", "/search", "/documents/upsert", "secret",
        "employee-portal", 10,
    )
    captured = {}

    def fake_post(path, payload, operation):
        captured.update({"path": path, "payload": payload, "operation": operation})
        return {"status": "ok"}

    monkeypatch.setattr(client, "_post", fake_post)
    result = client.upsert_documents([
        ParcleMemoryDocument(id="doc:1", title="Doc", content="Text", reference="README.md")
    ])

    assert captured["path"] == "/documents/upsert"
    assert captured["payload"]["namespace"] == "employee-portal"
    assert captured["payload"]["documents"][0]["id"] == "doc:1"
    assert result["location"] == "https://parcle.example/api namespace:employee-portal"
