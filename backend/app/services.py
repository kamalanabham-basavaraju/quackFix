from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.db.session import SessionLocal
from app.models.conversation import AppSetting, Conversation, IncidentExecution, Message
from app.websocket import manager


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def title_from_incident(incident: str) -> str:
    title = " ".join(incident.split())
    return title[:80] or "New incident"


def title_from_produck_ticket(ticket: dict[str, Any]) -> str:
    title = str(ticket.get("title") or "").strip()
    if not title or title == "Produck feedback":
        title = str(ticket.get("description") or ticket.get("ticket_id") or "Produck ticket").strip()
    return f"Produck: {title[:80]}"


def produck_ticket_id_from_conversation(conversation: Conversation) -> str | None:
    for tag in conversation.tags or []:
        value = str(tag)
        if value.startswith("produck:"):
            return value.split(":", 1)[1]
    return None


def produck_ticket_prompt(ticket: dict[str, Any]) -> str:
    ticket_id = str(ticket.get("ticket_id") or "unknown")
    title = str(ticket.get("title") or "Produck feedback")
    description = str(ticket.get("description") or "").strip()
    route = ticket.get("route") or "unknown"
    page_url = ticket.get("page_url") or ""
    annotations = ticket.get("annotations") or []
    annotation_lines = []
    for annotation in annotations[:5]:
        if not isinstance(annotation, dict):
            continue
        text = annotation.get("interpreted_text") or annotation.get("text") or annotation.get("type")
        if text:
            annotation_lines.append(f"- {text}")
    annotation_text = "\n".join(annotation_lines) or "- No annotation text found"
    page_line = f"\nPage URL: {page_url}" if page_url else ""
    return (
        f"Produck ticket `{ticket_id}` was fetched and is waiting for your approval.\n\n"
        f"Title: {title}\n"
        f"Route: {route}{page_line}\n\n"
        f"Description:\n{description or 'No description provided.'}\n\n"
        f"Annotations:\n{annotation_text}\n\n"
        "Choose **Fix / answer ticket** when you want Quackfix to action this item."
    )


def get_setting(db: Session, key: str, default: dict[str, Any]) -> AppSetting:
    setting = db.get(AppSetting, key)
    if setting is None:
        setting = AppSetting(key=key, value=default, updated_at=now_utc())
        db.add(setting)
        db.commit()
        db.refresh(setting)
    return setting


def serialize_conversation(conversation: Conversation) -> Conversation:
    return conversation


async def update_execution_stage(execution_id: str, stage: str, status: str = "running") -> None:
    with SessionLocal() as db:
        execution = db.get(IncidentExecution, execution_id)
        if execution is None:
            return
        execution.stage = stage
        execution.status = status
        db.commit()
        await manager.broadcast(
            execution_id,
            {
                "type": "execution_update",
                "execution_id": execution_id,
                "status": execution.status,
                "stage": execution.stage,
                "timestamp": now_utc().isoformat(),
            },
        )


async def process_incident_execution(
    execution_id: str,
    incident: str,
    employee_portal_path: str | None = None,
) -> None:
    await update_execution_stage(execution_id, "running")
    await asyncio.sleep(0.25)
    await update_execution_stage(execution_id, "searching_parcle")
    await asyncio.sleep(0.25)
    await update_execution_stage(execution_id, "analyzing")
    await asyncio.sleep(0.25)
    await update_execution_stage(execution_id, "generating_fix")

    started = now_utc()
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            request_payload: dict[str, Any] = {"incident": incident}
            if employee_portal_path:
                request_payload["employee_portal_path"] = employee_portal_path
            response = await client.post(
                f"{settings.langgraph_url.rstrip('/')}/api/v1/incidents/resolve",
                json=request_payload,
            )
            response.raise_for_status()
            payload = response.json()

        await update_execution_stage(execution_id, "validating")
        await asyncio.sleep(0.2)
        await update_execution_stage(execution_id, "creating_pr")

        with SessionLocal() as db:
            execution = db.get(IncidentExecution, execution_id)
            if execution is None:
                return
            execution.status = "completed"
            execution.stage = "completed"
            execution.completed_at = now_utc()
            execution.summary = payload.get("summary")
            execution.branch_name = payload.get("branch_name")
            execution.commit_hash = payload.get("commit_hash")
            execution.pull_request_url = payload.get("pull_request_url")
            execution.incident_record_path = payload.get("incident_record_path")
            execution.files_modified = payload.get("files_modified") or []
            execution.documentation_updated = bool(payload.get("documentation_updated"))
            execution.validation = payload.get("validation") or {}
            execution.raw_response = payload
            db.add(
                Message(
                    conversation_id=execution.conversation_id,
                    role="assistant",
                    content=assistant_summary(payload),
                )
            )
            conversation = db.get(Conversation, execution.conversation_id)
            if conversation:
                conversation.updated_at = now_utc()
            db.commit()
            await manager.broadcast(
                execution_id,
                {
                    "type": "execution_update",
                    "execution_id": execution_id,
                    "status": "completed",
                    "stage": "completed",
                    "duration_seconds": (execution.completed_at - started).total_seconds(),
                    "result": payload,
                },
            )
    except Exception as exc:
        with SessionLocal() as db:
            execution = db.get(IncidentExecution, execution_id)
            if execution is None:
                return
            execution.status = "failed"
            execution.stage = "failed"
            execution.completed_at = now_utc()
            execution.error = str(exc)
            db.add(
                Message(
                    conversation_id=execution.conversation_id,
                    role="assistant",
                    content=f"I could not complete the incident resolution.\n\nError: {exc}",
                )
            )
            conversation = db.get(Conversation, execution.conversation_id)
            if conversation:
                conversation.updated_at = now_utc()
            db.commit()
            await manager.broadcast(
                execution_id,
                {
                    "type": "execution_update",
                    "execution_id": execution_id,
                    "status": "failed",
                    "stage": "failed",
                    "error": str(exc),
                },
            )


def assistant_summary(payload: dict[str, Any]) -> str:
    validation = payload.get("validation") or {}
    if validation.get("skipped"):
        return payload.get("summary") or "Done."
    if payload.get("pull_request_url"):
        return f"Fix applied. PR raised: {payload['pull_request_url']}"
    return "Fix applied."


async def fetch_produck_tickets_into_history() -> dict[str, Any]:
    with SessionLocal() as db:
        target_repo = get_setting(db, "target_repo", {"employee_portal_path": ""})
        employee_portal_path = target_repo.value.get("employee_portal_path") or None
    request_payload: dict[str, Any] = {}
    if employee_portal_path:
        request_payload["employee_portal_path"] = employee_portal_path
    async with httpx.AsyncClient(timeout=None) as client:
        response = await client.post(
            f"{settings.langgraph_url.rstrip('/')}/api/v1/produck/tickets/open",
            json=request_payload or None,
        )
        response.raise_for_status()
        payload = response.json()

    tickets = payload.get("tickets") or []
    added = 0
    updated = 0
    conversations: list[Conversation] = []
    with SessionLocal() as db:
        existing = list(db.scalars(select(Conversation).where(Conversation.category == "produck")).all())
        by_ticket_id = {
            ticket_id: conversation
            for conversation in existing
            if (ticket_id := produck_ticket_id_from_conversation(conversation))
        }
        for ticket in tickets:
            if not isinstance(ticket, dict):
                continue
            ticket_id = str(ticket.get("ticket_id") or "")
            if not ticket_id:
                continue
            conversation = by_ticket_id.get(ticket_id)
            if conversation is None:
                conversation = Conversation(
                    title=title_from_produck_ticket(ticket),
                    severity="medium",
                    category="produck",
                    tags=["produck", f"produck:{ticket_id}", "source:produck"],
                )
                db.add(conversation)
                db.flush()
                db.add(Message(conversation_id=conversation.id, role="user", content=produck_ticket_prompt(ticket)))
                db.add(
                    Message(
                        conversation_id=conversation.id,
                        role="assistant",
                        content="Ticket fetched from Produck. I have not actioned it yet.",
                    )
                )
                added += 1
            else:
                conversation.title = title_from_produck_ticket(ticket)
                conversation.updated_at = now_utc()
                updated += 1
            conversations.append(conversation)
        db.commit()
        ids = [conversation.id for conversation in conversations]
        loaded = list(
            db.scalars(
                select(Conversation)
                .where(Conversation.id.in_(ids))
                .options(selectinload(Conversation.messages), selectinload(Conversation.executions))
            )
            .unique()
            .all()
        ) if ids else []
    return {
        "checked_at": payload.get("checked_at"),
        "fetched": payload.get("fetched", 0),
        "added": added,
        "updated": updated,
        "skipped_processed": payload.get("skipped_processed", 0),
        "failures": payload.get("failures", 0),
        "conversations": loaded,
    }


async def process_produck_ticket_execution(
    execution_id: str,
    ticket_id: str,
    employee_portal_path: str | None = None,
) -> None:
    await update_execution_stage(execution_id, "running")
    await asyncio.sleep(0.25)
    await update_execution_stage(execution_id, "fetching_produck_ticket")
    await asyncio.sleep(0.25)
    await update_execution_stage(execution_id, "generating_fix")
    started = now_utc()
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            request_payload: dict[str, Any] = {}
            if employee_portal_path:
                request_payload["employee_portal_path"] = employee_portal_path
            response = await client.post(
                f"{settings.langgraph_url.rstrip('/')}/api/v1/produck/tickets/{ticket_id}/trigger",
                json=request_payload or None,
            )
            response.raise_for_status()
            payload = response.json()

        await update_execution_stage(execution_id, "validating")
        await asyncio.sleep(0.2)
        await update_execution_stage(execution_id, "creating_pr")

        with SessionLocal() as db:
            execution = db.get(IncidentExecution, execution_id)
            if execution is None:
                return
            execution.status = "completed"
            execution.stage = "completed"
            execution.completed_at = now_utc()
            execution.summary = payload.get("summary")
            execution.branch_name = payload.get("branch_name")
            execution.commit_hash = payload.get("commit_hash")
            execution.pull_request_url = payload.get("pull_request_url")
            execution.incident_record_path = payload.get("incident_record_path")
            execution.files_modified = payload.get("files_modified") or []
            execution.documentation_updated = bool(payload.get("documentation_updated"))
            execution.validation = payload.get("validation") or {}
            execution.raw_response = payload
            db.add(
                Message(
                    conversation_id=execution.conversation_id,
                    role="assistant",
                    content=assistant_summary(payload) if not payload.get("skipped") else str(payload.get("reason") or "Ticket skipped."),
                )
            )
            conversation = db.get(Conversation, execution.conversation_id)
            if conversation:
                conversation.updated_at = now_utc()
            db.commit()
            await manager.broadcast(
                execution_id,
                {
                    "type": "execution_update",
                    "execution_id": execution_id,
                    "status": "completed",
                    "stage": "completed",
                    "duration_seconds": (execution.completed_at - started).total_seconds(),
                    "result": payload,
                },
            )
    except Exception as exc:
        with SessionLocal() as db:
            execution = db.get(IncidentExecution, execution_id)
            if execution is None:
                return
            execution.status = "failed"
            execution.stage = "failed"
            execution.completed_at = now_utc()
            execution.error = str(exc)
            db.add(
                Message(
                    conversation_id=execution.conversation_id,
                    role="assistant",
                    content=f"I could not complete the Produck ticket.\n\nError: {exc}",
                )
            )
            conversation = db.get(Conversation, execution.conversation_id)
            if conversation:
                conversation.updated_at = now_utc()
            db.commit()
            await manager.broadcast(
                execution_id,
                {
                    "type": "execution_update",
                    "execution_id": execution_id,
                    "status": "failed",
                    "stage": "failed",
                    "error": str(exc),
                },
            )


async def produck_auto_poll_loop() -> None:
    while True:
        await asyncio.sleep(settings.produck_poll_interval_seconds)
        with SessionLocal() as db:
            setting = get_setting(db, "produck_auto_fetch", {"enabled": False})
            enabled = bool(setting.value.get("enabled"))
        if not enabled:
            continue
        try:
            await fetch_produck_tickets_into_history()
        except Exception:
            continue


def conversation_query(db: Session):
    return (
        select(Conversation)
        .options(selectinload(Conversation.messages), selectinload(Conversation.executions))
        .order_by(Conversation.updated_at.desc())
    )


def dashboard_payload(db: Session) -> dict[str, Any]:
    executions = db.scalars(select(IncidentExecution)).all()
    total = len(executions)
    success = len([item for item in executions if item.status == "completed"])
    failed = len([item for item in executions if item.status == "failed"])
    open_prs = len([item for item in executions if item.pull_request_url and item.status == "completed"])
    durations = [
        (item.completed_at - item.started_at).total_seconds()
        for item in executions
        if item.completed_at is not None
    ]
    by_day: dict[str, int] = {}
    for item in executions:
        key = item.started_at.date().isoformat()
        by_day[key] = by_day.get(key, 0) + 1
    return {
        "total_incidents": total,
        "successful_resolutions": success,
        "failed_resolutions": failed,
        "open_prs": open_prs,
        "average_resolution_seconds": sum(durations) / len(durations) if durations else 0,
        "incidents_by_day": [{"date": key, "count": value} for key, value in sorted(by_day.items())],
        "success_rate": [
            {"name": "successful", "value": success},
            {"name": "failed", "value": failed},
            {"name": "other", "value": max(total - success - failed, 0)},
        ],
        "resolution_duration": [
            {"execution_id": item.id, "seconds": (item.completed_at - item.started_at).total_seconds()}
            for item in executions
            if item.completed_at is not None
        ][-20:],
    }


def search_payload(db: Session, query: str) -> list[dict[str, Any]]:
    pattern = f"%{query}%"
    rows = db.execute(
        select(Conversation, Message, IncidentExecution)
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .outerjoin(IncidentExecution, IncidentExecution.conversation_id == Conversation.id)
        .where(
            or_(
                Conversation.title.ilike(pattern),
                Message.content.ilike(pattern),
                IncidentExecution.summary.ilike(pattern),
            )
        )
        .order_by(Conversation.updated_at.desc())
        .limit(50)
    ).all()
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for conversation, message, execution in rows:
        if conversation.id in seen:
            continue
        seen.add(conversation.id)
        snippet = conversation.title
        if message and query.lower() in message.content.lower():
            snippet = message.content[:240]
        elif execution and execution.summary:
            snippet = execution.summary[:240]
        results.append(
            {
                "conversation_id": conversation.id,
                "title": conversation.title,
                "snippet": snippet,
                "status": execution.status if execution else None,
                "updated_at": conversation.updated_at,
            }
        )
    return results
