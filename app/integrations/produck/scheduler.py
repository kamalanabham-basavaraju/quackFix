from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.integrations.parcle import ParcleClient
from app.integrations.produck.client import ProduckClient
from app.integrations.produck.metrics import ProduckMetrics
from app.integrations.produck.state_store import ProduckStateStore
from app.integrations.produck.ticket_mapper import (
    compact_location_evidence,
    compact_ticket_evidence,
    ticket_fingerprint,
    ticket_memory_markdown,
)
from app.models.incident import ParcleMemoryDocument
from app.models.produck import NormalizedProduckRequest, ProduckPollResult, ProduckTicket

logger = logging.getLogger(__name__)


class GraphRunner(Protocol):
    def invoke(self, input: dict[str, Any]) -> dict[str, Any]:
        ...


class ProduckScheduler:
    def __init__(
        self,
        client: ProduckClient,
        parcle: ParcleClient,
        groq: Any,
        graph: GraphRunner,
        state_store: ProduckStateStore,
        feedback_ids: tuple[str, ...],
        poll_interval_seconds: int,
        close_on_success: bool = False,
    ):
        self.client = client
        self.parcle = parcle
        self.groq = groq
        self.graph = graph
        self.state_store = state_store
        self.feedback_ids = feedback_ids
        self.poll_interval_seconds = poll_interval_seconds
        self.close_on_success = close_on_success
        self.metrics = ProduckMetrics()
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="produck-scheduler")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            await self._task

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.poll_once()
            except Exception as exc:
                self.metrics.failures += 1
                self.metrics.dead_letters.append({"ticket_id": "poll", "error": str(exc)})
                logger.exception("Produck poll failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval_seconds)
            except asyncio.TimeoutError:
                continue

    async def poll_once(self) -> ProduckPollResult:
        checked_at = datetime.now(timezone.utc)
        result = ProduckPollResult(checked_at=checked_at)
        self.metrics.polls += 1
        summaries = await self.client.fetch_open_ticket_summaries(self.feedback_ids)
        result.fetched = len(summaries)
        for summary in summaries:
            ticket_id = str(summary.get("feedback_id") or "")
            if not ticket_id:
                continue
            if self.state_store.is_processed(ticket_id):
                result.duplicates += 1
                self.metrics.duplicates_skipped += 1
                continue
            try:
                ticket = await self.client.fetch_ticket(ticket_id)
                self.metrics.tickets_fetched += 1
            except Exception as exc:
                result.failures += 1
                self.metrics.failures += 1
                self.metrics.dead_letters.append({"ticket_id": ticket_id, "error": str(exc)})
                self.state_store.mark_failed(ticket_id, "", str(exc))
                logger.exception("Produck full ticket fetch failed", extra={"ticket_id": ticket_id})
                continue
            fingerprint = ticket_fingerprint(ticket)
            if not self.state_store.should_process(ticket.ticket_id, fingerprint):
                result.duplicates += 1
                self.metrics.duplicates_skipped += 1
                continue
            self.state_store.mark_seen(ticket.ticket_id, fingerprint)
            try:
                if self.close_on_success:
                    await self._try_update_status(
                        ticket.ticket_id,
                        "in_progress",
                        "LangGraph agent started processing",
                    )
                state = await self.process_ticket(ticket)
                workflow_run_id = str(state.get("run_id") or "")
                self.state_store.mark_processed(ticket.ticket_id, fingerprint, workflow_run_id)
                result.processed += 1
                result.triggered += 1
                result.tickets.append(ticket.ticket_id)
                self.metrics.tickets_processed += 1
                self.metrics.workflow_runs += 1
                if self.close_on_success:
                    await self._try_update_status(ticket.ticket_id, "resolved", str(state.get("summary", ""))[:1000])
            except Exception as exc:
                result.failures += 1
                self.metrics.failures += 1
                self.metrics.dead_letters.append({"ticket_id": ticket.ticket_id, "error": str(exc)})
                self.state_store.mark_failed(ticket.ticket_id, fingerprint, str(exc))
                logger.exception("Produck ticket processing failed", extra={"ticket_id": ticket.ticket_id})
        return result

    async def _try_update_status(self, ticket_id: str, status: str, note: str = "") -> None:
        try:
            result = await self.client.update_ticket_status(ticket_id, status, note)
            if result is None:
                logger.info("Produck status update skipped; no MCP status tool found", extra={"ticket_id": ticket_id})
        except Exception:
            logger.exception("Produck status update failed", extra={"ticket_id": ticket_id, "status": status})

    async def process_ticket(self, ticket: ProduckTicket) -> dict[str, Any]:
        self._store_ticket_in_parcle(ticket)
        normalized = self._normalize_ticket(ticket)
        evidence = compact_ticket_evidence(ticket)
        return self.graph.invoke(
            {
                "incident": normalized.to_incident_prompt(),
                "parcle_query": normalized.to_parcle_query(),
                "produck_ticket_id": ticket.ticket_id,
                "produck_payload": evidence,
                "produck_brief": ticket.brief_markdown,
            }
        )

    def _normalize_ticket(self, ticket: ProduckTicket) -> NormalizedProduckRequest:
        normalizer = getattr(self.groq, "normalize_produck_ticket", None)
        if callable(normalizer):
            try:
                normalized = NormalizedProduckRequest.model_validate(normalizer(ticket))
                evidence = compact_ticket_evidence(ticket)
                normalized.context.update(
                    {
                        "compact_evidence": evidence,
                        "location_evidence": compact_location_evidence(evidence),
                    }
                )
                return normalized
            except Exception:
                logger.exception("Falling back to deterministic Produck normalization")
        evidence = compact_ticket_evidence(ticket)
        feedback = evidence["feedback"]
        location_evidence = compact_location_evidence(evidence)
        return NormalizedProduckRequest(
            ticket_id=ticket.ticket_id,
            classification="ux",
            priority="medium",
            summary=str(feedback.get("complaint_interpreted") or ticket.title),
            problem_statement=str(feedback.get("complaint_interpreted") or ticket.description),
            reproduction_steps=[
                f"Open {feedback.get('page_url') or feedback.get('route') or 'the reported route'}.",
                "Use the Produck annotation coordinates and screen size to locate the reported UI area.",
                location_evidence,
            ],
            affected_route=str(feedback.get("route") or ticket.route or ""),
            suggested_fix=str(ticket.design_doc.get("proposed_fix") or ""),
            confidence=0.5,
            context={"compact_evidence": evidence, "location_evidence": location_evidence},
        )

    def _store_ticket_in_parcle(self, ticket: ProduckTicket) -> None:
        document = ParcleMemoryDocument(
            id=f"produck:{ticket.ticket_id}",
            title=f"Produck feedback - {ticket.title}",
            content=ticket_memory_markdown(ticket),
            reference=f"produck:{ticket.ticket_id}",
            metadata={
                "content_type": "produck_ticket",
                "ticket_id": ticket.ticket_id,
                "route": ticket.route,
                "page_url": ticket.page_url,
            },
        )
        self.parcle.ingest_documents([document])


def build_produck_scheduler(
    *,
    client: ProduckClient,
    parcle: ParcleClient,
    groq: Any,
    graph: GraphRunner,
    state_path: Path,
    legacy_state_path: Path | None = None,
    feedback_ids: tuple[str, ...],
    poll_interval_seconds: int,
    close_on_success: bool,
) -> ProduckScheduler:
    state_store = ProduckStateStore(state_path)
    state_store.bootstrap_from(legacy_state_path)
    return ProduckScheduler(
        client=client,
        parcle=parcle,
        groq=groq,
        graph=graph,
        state_store=state_store,
        feedback_ids=feedback_ids,
        poll_interval_seconds=poll_interval_seconds,
        close_on_success=close_on_success,
    )
