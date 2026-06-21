from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.integrations.produck.state_store import ProduckStateStore
from app.integrations.produck.ticket_fetcher import ProduckTicketFetcher
from app.integrations.produck.ticket_mapper import (
    compact_location_evidence,
    compact_ticket_evidence,
    ticket_fingerprint,
    ticket_from_payload,
)


def test_produck_payload_maps_to_ticket():
    payload = {
        "feedback": {
            "id": "ticket-1",
            "created_at": "2026-06-20T10:34:25Z",
            "page_url": "https://example.test/app/mcp",
            "route": "/app/mcp",
            "complaint_interpreted": "This color is not great",
        },
        "annotations": [{"index": 0, "type": "marker", "interpreted_text": "This color is not great"}],
        "design_doc": {"proposed_fix": "Improve the color contrast."},
    }

    ticket = ticket_from_payload(payload, "# Brief")

    assert ticket.ticket_id == "ticket-1"
    assert ticket.route == "/app/mcp"
    assert ticket.description == "This color is not great"
    assert ticket.annotations[0].interpreted_text == "This color is not great"
    assert ticket_fingerprint(ticket)


def test_compact_ticket_evidence_keeps_coordinates_without_raw_html():
    payload = {
        "feedback": {
            "id": "ticket-1",
            "page_url": "https://example.test/app/mcp",
            "route": "/app/mcp",
            "complaint_interpreted": "This color is not great",
        },
        "capture_environment": {"screen": {"width": 1875, "height": 951, "devicePixelRatio": 1}},
        "annotations": [
            {
                "index": 0,
                "type": "marker",
                "interpreted_text": "This color is not great",
                "anchor": {"x": 1209, "y": 697},
                "anchor_percent": {"x": 64.48, "y": 73.29},
                "locator_confidence": "low",
            }
        ],
        "page_snapshot_summary": {"visible_text_excerpt": "x" * 5000},
    }
    ticket = ticket_from_payload(payload, raw={"content": [{"text": "<html>" + ("x" * 50000)}]})

    evidence = compact_ticket_evidence(ticket)
    location = compact_location_evidence(evidence)

    assert evidence["annotations"][0]["anchor"] == {"x": 1209, "y": 697}
    assert evidence["annotations"][0]["anchor_percent"] == {"x": 64.48, "y": 73.29}
    assert len(evidence["page_snapshot_summary"]["visible_text_excerpt"]) < 1300
    assert "anchor_px={'x': 1209, 'y': 697}" in location
    assert "raw" not in evidence


def test_produck_state_store_dedupes_by_fingerprint(tmp_path: Path):
    store = ProduckStateStore(tmp_path / "state.json")

    assert store.should_process("ticket-1", "abc") is True
    store.mark_processed("ticket-1", "abc", "run-1")
    assert store.should_process("ticket-1", "abc") is False
    assert store.should_process("ticket-1", "def") is True
    assert store.is_processed("ticket-1") is True


def test_produck_state_store_bootstraps_legacy_state(tmp_path: Path):
    legacy = tmp_path / "employee/docs/parcle_memory/.state/produck_ticket_state.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        '{"ticket-1":{"ticket_id":"ticket-1","status":"processed","last_seen":"now","fingerprint":"abc"}}',
        encoding="utf-8",
    )
    store = ProduckStateStore(tmp_path / "runtime/produck_ticket_state.json")

    store.bootstrap_from(legacy)

    assert store.is_processed("ticket-1") is True


def test_produck_search_feedback_response_extracts_open_ids():
    raw = {
        "content": [
            {
                "type": "text",
                "text": (
                    '{"items":['
                    '{"feedbackId":"open-1","firstAnnotationText":"Fix color","isSpam":false},'
                    '{"feedbackId":"progress-1","status":"in_progress","isSpam":false},'
                    '{"feedbackId":"spam-1","firstAnnotationText":"Ignore","isSpam":true},'
                    '{"feedbackId":"closed-1","status":"resolved","isSpam":false}'
                    '],"nextCursor":"cursor-2","count":3}'
                ),
            }
        ],
        "isError": False,
    }

    summaries, cursor = ProduckTicketFetcher._extract_feedback_summaries(raw)

    assert [item["feedback_id"] for item in summaries] == ["open-1"]
    assert summaries[0]["summary"] == "Fix color"
    assert cursor == "cursor-2"


def test_produck_search_arguments_include_open_status_when_supported():
    fetcher = ProduckTicketFetcher(connector=None, output_dir=Path("."))  # type: ignore[arg-type]
    tool = {
        "inputSchema": {
            "properties": {
                "limit": {"type": "integer"},
                "cursor": {"type": "string"},
                "status": {"type": "string"},
            }
        }
    }

    args = fetcher._build_search_arguments(tool, "cursor-1")

    assert args == {"limit": 50, "cursor": "cursor-1", "status": "open"}


def test_produck_open_fetch_limits_full_ticket_fetches(monkeypatch, tmp_path: Path):
    class Connector:
        async def list_tools(self):
            return [
                {"name": "search_feedback", "inputSchema": {"properties": {"limit": {"type": "integer"}}}},
                {"name": "get_feedback", "inputSchema": {"properties": {"feedbackId": {"type": "string"}}}},
            ]

    fetcher = ProduckTicketFetcher(
        connector=Connector(),  # type: ignore[arg-type]
        output_dir=tmp_path,
        max_tickets_per_poll=1,
    )

    async def fake_search(tool):
        return [{"feedback_id": "ticket-1"}, {"feedback_id": "ticket-2"}]

    fetched: list[str] = []

    async def fake_fetch(feedback_id):
        fetched.append(feedback_id)
        return ticket_from_payload({"feedback": {"id": feedback_id, "complaint_interpreted": "Issue"}})

    monkeypatch.setattr(fetcher, "_search_open_feedback", fake_search)
    monkeypatch.setattr(fetcher, "fetch_ticket", fake_fetch)

    import asyncio

    tickets = asyncio.run(fetcher.fetch_open_tickets())

    assert [ticket.ticket_id for ticket in tickets] == ["ticket-1"]
    assert fetched == ["ticket-1"]


def test_relative_produck_paths_resolve_under_employee_memory(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("EMPLOYEE_PORTAL_PATH", str(tmp_path))
    monkeypatch.setenv("PARCLE_MEMORY_DIR", "docs/parcle_memory")
    monkeypatch.setenv("PRODUCK_OUTPUT_DIR", "produck_out")
    monkeypatch.setenv("PRODUCK_STATE_PATH", ".state/produck_ticket_state.json")

    settings = Settings.from_env()

    assert settings.produck_output_dir == tmp_path / "docs/parcle_memory/produck_out"
    assert settings.produck_state_path == Path.home() / ".langgraph-starter/.state/produck_ticket_state.json"
    assert settings.produck_legacy_state_path == tmp_path / "docs/parcle_memory/.state/produck_ticket_state.json"
