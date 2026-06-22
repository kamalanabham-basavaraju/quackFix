from __future__ import annotations

import asyncio
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.db.session import get_db
from app.models.conversation import Conversation, IncidentExecution, Message, now_utc
from app.schemas import (
    ConversationCreate,
    ConversationOut,
    DashboardOut,
    ExecutionOut,
    IncidentSubmit,
    IncidentSubmitResponse,
    ProduckFetchSetting,
    ProduckFetchSettingOut,
    ProduckPollHistoryResponse,
    ProduckTriggerResponse,
    SearchResult,
    TargetRepoSetting,
    TargetRepoSettingOut,
)
from app.services import (
    conversation_query,
    dashboard_payload,
    fetch_produck_tickets_into_history,
    get_setting,
    process_incident_execution,
    process_produck_ticket_execution,
    produck_auto_poll_loop,
    produck_ticket_id_from_conversation,
    search_payload,
    title_from_incident,
)
from app.websocket import manager

app = FastAPI(title="Quackfix Portal API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    asyncio.create_task(produck_auto_poll_loop())


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/conversations", response_model=ConversationOut)
def create_conversation(payload: ConversationCreate, db: Session = Depends(get_db)) -> Conversation:
    conversation = Conversation(
        title=payload.title,
        severity=payload.severity,
        category=payload.category,
        tags=payload.tags,
    )
    db.add(conversation)
    db.commit()
    return db.scalars(
        select(Conversation)
        .where(Conversation.id == conversation.id)
        .options(selectinload(Conversation.messages), selectinload(Conversation.executions))
    ).one()


@app.get("/api/conversations", response_model=list[ConversationOut])
def list_conversations(
    status: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
) -> list[Conversation]:
    statement = conversation_query(db)
    conversations = list(db.scalars(statement).unique().all())
    if status and status != "all":
        conversations = [
            item for item in conversations if item.executions and item.executions[-1].status == status
        ]
    if q:
        needle = q.lower()
        conversations = [
            item
            for item in conversations
            if needle in item.title.lower()
            or any(needle in message.content.lower() for message in item.messages)
            or any(execution.summary and needle in execution.summary.lower() for execution in item.executions)
        ]
    return conversations


@app.get("/api/conversations/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: str, db: Session = Depends(get_db)) -> Conversation:
    conversation = db.scalars(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages), selectinload(Conversation.executions))
    ).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.post("/api/incidents/submit", response_model=IncidentSubmitResponse)
async def submit_incident(payload: IncidentSubmit, db: Session = Depends(get_db)) -> dict[str, Any]:
    repo_setting = get_setting(db, "target_repo", {"employee_portal_path": ""})
    employee_portal_path = payload.employee_portal_path or repo_setting.value.get("employee_portal_path") or None
    conversation = db.get(Conversation, payload.conversation_id) if payload.conversation_id else None
    if conversation is None:
        conversation = Conversation(
            title=title_from_incident(payload.incident),
            severity=payload.severity,
            category=payload.category,
            tags=payload.tags,
        )
        db.add(conversation)
        db.flush()
    conversation.updated_at = now_utc()
    db.add(Message(conversation_id=conversation.id, role="user", content=payload.incident))
    db.add(Message(conversation_id=conversation.id, role="assistant", content="Analyzing incident..."))
    execution = IncidentExecution(conversation_id=conversation.id, status="queued", stage="queued")
    db.add(execution)
    db.commit()
    db.refresh(execution)
    conversation = db.scalars(
        select(Conversation)
        .where(Conversation.id == conversation.id)
        .options(selectinload(Conversation.messages), selectinload(Conversation.executions))
    ).unique().one()
    asyncio.create_task(process_incident_execution(execution.id, payload.incident, employee_portal_path))
    return {"conversation": conversation, "execution": execution}


@app.get("/api/executions/{execution_id}", response_model=ExecutionOut)
def get_execution(execution_id: str, db: Session = Depends(get_db)) -> IncidentExecution:
    execution = db.get(IncidentExecution, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution


@app.websocket("/ws/executions/{execution_id}")
async def execution_ws(websocket: WebSocket, execution_id: str) -> None:
    await manager.connect(execution_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(execution_id, websocket)


@app.get("/api/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db)) -> dict[str, Any]:
    return dashboard_payload(db)


@app.get("/api/search", response_model=list[SearchResult])
def search(q: str, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    if not q.strip():
        return []
    return search_payload(db, q.strip())


@app.get("/api/conversations/{conversation_id}/export")
def export_conversation(conversation_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    conversation = get_conversation(conversation_id, db)
    return ConversationOut.model_validate(conversation).model_dump(mode="json")


@app.get("/api/settings/produck-fetch", response_model=ProduckFetchSettingOut)
def get_produck_fetch_setting(db: Session = Depends(get_db)) -> dict[str, Any]:
    setting = get_setting(db, "produck_auto_fetch", {"enabled": False})
    return {"enabled": bool(setting.value.get("enabled")), "updated_at": setting.updated_at}


@app.put("/api/settings/produck-fetch", response_model=ProduckFetchSettingOut)
def set_produck_fetch_setting(payload: ProduckFetchSetting, db: Session = Depends(get_db)) -> dict[str, Any]:
    setting = get_setting(db, "produck_auto_fetch", {"enabled": False})
    setting.value = {"enabled": payload.enabled}
    setting.updated_at = now_utc()
    db.commit()
    return {"enabled": payload.enabled, "updated_at": setting.updated_at}


@app.get("/api/settings/target-repo", response_model=TargetRepoSettingOut)
def get_target_repo_setting(db: Session = Depends(get_db)) -> dict[str, Any]:
    setting = get_setting(db, "target_repo", {"employee_portal_path": ""})
    return {
        "employee_portal_path": str(setting.value.get("employee_portal_path") or ""),
        "updated_at": setting.updated_at,
    }


@app.put("/api/settings/target-repo", response_model=TargetRepoSettingOut)
def set_target_repo_setting(payload: TargetRepoSetting, db: Session = Depends(get_db)) -> dict[str, Any]:
    setting = get_setting(db, "target_repo", {"employee_portal_path": ""})
    setting.value = {"employee_portal_path": payload.employee_portal_path.strip()}
    setting.updated_at = now_utc()
    db.commit()
    return {
        "employee_portal_path": payload.employee_portal_path.strip(),
        "updated_at": setting.updated_at,
    }


@app.post("/api/produck/poll", response_model=ProduckPollHistoryResponse)
async def poll_produck() -> dict[str, Any]:
    try:
        return await fetch_produck_tickets_into_history()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/produck/conversations/{conversation_id}/trigger", response_model=ProduckTriggerResponse)
async def trigger_produck_conversation(conversation_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    conversation = db.scalars(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages), selectinload(Conversation.executions))
    ).unique().first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conversation.category != "produck":
        raise HTTPException(status_code=400, detail="Conversation is not a Produck ticket")
    ticket_id = produck_ticket_id_from_conversation(conversation)
    if not ticket_id:
        raise HTTPException(status_code=400, detail="Produck ticket id is missing")

    repo_setting = get_setting(db, "target_repo", {"employee_portal_path": ""})
    employee_portal_path = repo_setting.value.get("employee_portal_path") or None
    db.add(Message(conversation_id=conversation.id, role="assistant", content="Working on this Produck ticket now..."))
    execution = IncidentExecution(conversation_id=conversation.id, status="queued", stage="queued")
    db.add(execution)
    conversation.updated_at = now_utc()
    db.commit()
    db.refresh(execution)
    conversation = db.scalars(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages), selectinload(Conversation.executions))
    ).unique().one()
    asyncio.create_task(process_produck_ticket_execution(execution.id, ticket_id, employee_portal_path))
    return {"conversation": conversation, "execution": execution}
