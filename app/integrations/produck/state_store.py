from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.models.produck import ProduckTicketState


class ProduckStateStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, ProduckTicketState]:
        if not self.path.is_file():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        return {key: ProduckTicketState.model_validate(value) for key, value in payload.items()}

    def save(self, states: dict[str, ProduckTicketState]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({key: state.model_dump(mode="json") for key, state in states.items()}, indent=2),
            encoding="utf-8",
        )

    def bootstrap_from(self, legacy_path: Path | None) -> None:
        if self.path.exists() or legacy_path is None or not legacy_path.is_file() or legacy_path == self.path:
            return
        payload = json.loads(legacy_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return
        states = {key: ProduckTicketState.model_validate(value) for key, value in payload.items()}
        self.save(states)

    def should_process(self, ticket_id: str, fingerprint: str) -> bool:
        state = self.load().get(ticket_id)
        return state is None or state.fingerprint != fingerprint or state.status == "failed"

    def is_processed(self, ticket_id: str) -> bool:
        state = self.load().get(ticket_id)
        return state is not None and state.status == "processed"

    def mark_seen(self, ticket_id: str, fingerprint: str) -> None:
        states = self.load()
        states[ticket_id] = ProduckTicketState(
            ticket_id=ticket_id,
            status="seen",
            last_seen=datetime.now(timezone.utc).isoformat(),
            fingerprint=fingerprint,
        )
        self.save(states)

    def mark_processed(self, ticket_id: str, fingerprint: str, workflow_run_id: str | None) -> None:
        states = self.load()
        states[ticket_id] = ProduckTicketState(
            ticket_id=ticket_id,
            status="processed",
            last_seen=datetime.now(timezone.utc).isoformat(),
            processed_at=datetime.now(timezone.utc).isoformat(),
            workflow_run_id=workflow_run_id,
            fingerprint=fingerprint,
        )
        self.save(states)

    def mark_failed(self, ticket_id: str, fingerprint: str, error: str) -> None:
        states = self.load()
        states[ticket_id] = ProduckTicketState(
            ticket_id=ticket_id,
            status="failed",
            last_seen=datetime.now(timezone.utc).isoformat(),
            fingerprint=fingerprint,
            error=error,
        )
        self.save(states)
