from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.graph.workflow import create_graph, graph
from app.config import settings
from app.integrations.produck.scheduler import build_produck_scheduler
from app.integrations.produck.ticket_mapper import ticket_fingerprint
from app.models.incident import IncidentRequest, IncidentResponse
from app.services.container import build_produck_client, build_services

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["incidents"])


class ProduckPollRequest(BaseModel):
    employee_portal_path: str | None = None


class ProduckTriggerRequest(BaseModel):
    employee_portal_path: str | None = None


@router.post("/incidents/resolve", response_model=IncidentResponse)
def resolve_incident(payload: IncidentRequest) -> IncidentResponse:
    try:
        active_graph = graph
        if payload.employee_portal_path:
            active_settings = settings.with_employee_portal_path(payload.employee_portal_path)
            active_graph = create_graph(build_services(active_settings))
        state = active_graph.invoke({"incident": payload.incident})
        return IncidentResponse.model_validate(state)
    except (ValueError, RuntimeError) as exc:
        logger.exception("Incident resolution failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected incident resolution failure")
        raise HTTPException(status_code=500, detail="Incident resolution failed") from exc


def _build_manual_produck_scheduler(active_settings = settings):
    services = build_services(active_settings)
    client = build_produck_client(active_settings, services.groq)
    return build_produck_scheduler(
        client=client,
        parcle=services.parcle,
        groq=services.groq,
        graph=create_graph(services),
        state_path=active_settings.produck_state_path,
        legacy_state_path=active_settings.produck_legacy_state_path,
        feedback_ids=active_settings.produck_feedback_ids,
        poll_interval_seconds=active_settings.produck_poll_interval_seconds,
        close_on_success=active_settings.produck_close_on_success,
    )


def _app_scheduler(request: Request):
    return getattr(request.app.state, "produck_scheduler", None)


@router.get("/produck/tools", tags=["produck"])
async def list_produck_tools() -> dict[str, Any]:
    try:
        client = build_produck_client(settings, build_services().groq)
        return {"tools": await client.list_tools()}
    except Exception as exc:
        logger.exception("Produck tool listing failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/produck/tickets/open", tags=["produck"])
async def fetch_open_produck_tickets(request: Request, payload: ProduckPollRequest | None = None) -> dict[str, Any]:
    employee_portal_path = payload.employee_portal_path if payload else None
    scheduler = None if employee_portal_path else _app_scheduler(request)
    if scheduler is None:
        scheduler = _build_manual_produck_scheduler(settings.with_employee_portal_path(employee_portal_path))
    try:
        summaries = await scheduler.client.fetch_open_ticket_summaries(scheduler.feedback_ids)
        tickets = []
        skipped_processed = 0
        failures = 0
        for summary in summaries:
            feedback_id = str(summary.get("feedback_id") or "")
            if not feedback_id:
                continue
            if scheduler.state_store.is_processed(feedback_id):
                skipped_processed += 1
                continue
            try:
                ticket = await scheduler.client.fetch_ticket(feedback_id)
                fingerprint = ticket_fingerprint(ticket)
                if not scheduler.state_store.should_process(ticket.ticket_id, fingerprint):
                    skipped_processed += 1
                    continue
                payload = ticket.model_dump(mode="json")
                payload["fingerprint"] = fingerprint
                tickets.append(payload)
            except Exception:
                failures += 1
                logger.exception("Produck ticket preview fetch failed", extra={"ticket_id": feedback_id})
        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "fetched": len(summaries),
            "tickets": tickets,
            "skipped_processed": skipped_processed,
            "failures": failures,
        }
    except Exception as exc:
        logger.exception("Produck ticket preview failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/produck/tickets/{feedback_id}/trigger", tags=["produck"])
async def trigger_produck_ticket(
    feedback_id: str,
    request: Request,
    payload: ProduckTriggerRequest | None = None,
) -> dict[str, Any]:
    employee_portal_path = payload.employee_portal_path if payload else None
    scheduler = None if employee_portal_path else _app_scheduler(request)
    if scheduler is None:
        scheduler = _build_manual_produck_scheduler(settings.with_employee_portal_path(employee_portal_path))
    try:
        if scheduler.state_store.is_processed(feedback_id):
            return {
                "ticket_id": feedback_id,
                "skipped": True,
                "reason": "ticket already processed",
            }
        ticket = await scheduler.client.fetch_ticket(feedback_id)
        fingerprint = ticket_fingerprint(ticket)
        if not scheduler.state_store.should_process(ticket.ticket_id, fingerprint):
            return {
                "ticket_id": ticket.ticket_id,
                "skipped": True,
                "reason": "ticket already processed with the same fingerprint",
            }
        scheduler.state_store.mark_seen(ticket.ticket_id, fingerprint)
        state = await scheduler.process_ticket(ticket)
        scheduler.state_store.mark_processed(ticket.ticket_id, fingerprint, str(state.get("run_id") or ""))
        return {
            "ticket_id": ticket.ticket_id,
            "skipped": False,
            "summary": state.get("summary"),
            "branch_name": state.get("branch_name"),
            "commit_hash": state.get("commit_hash"),
            "pull_request_url": state.get("pull_request_url"),
            "incident_record_path": state.get("incident_record_path"),
            "files_modified": state.get("files_modified"),
            "documentation_updated": state.get("documentation_updated"),
            "validation": state.get("validation"),
            "run_id": state.get("run_id"),
        }
    except Exception as exc:
        if "ticket" in locals() and "fingerprint" in locals():
            scheduler.state_store.mark_failed(ticket.ticket_id, fingerprint, str(exc))
        logger.exception("Produck ticket trigger failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/produck/poll", tags=["produck"])
async def poll_produck(request: Request, payload: ProduckPollRequest | None = None) -> dict[str, Any]:
    employee_portal_path = payload.employee_portal_path if payload else None
    scheduler = None if employee_portal_path else _app_scheduler(request)
    if scheduler is None:
        scheduler = _build_manual_produck_scheduler(settings.with_employee_portal_path(employee_portal_path))
    try:
        return (await scheduler.poll_once()).model_dump(mode="json")
    except Exception as exc:
        logger.exception("Produck poll failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/produck/state", tags=["produck"])
def produck_state(request: Request) -> dict[str, Any]:
    scheduler = _app_scheduler(request) or _build_manual_produck_scheduler()
    return {
        "tickets": {
            ticket_id: state.model_dump(mode="json")
            for ticket_id, state in scheduler.state_store.load().items()
        },
        "metrics": scheduler.metrics.snapshot(),
    }
