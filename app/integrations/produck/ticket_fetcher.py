from __future__ import annotations

import logging
import json
from typing import Any

from app.integrations.groq import GroqIncidentAnalyzer
from app.integrations.produck.mcp_connector import ProduckMcpConnector
from app.integrations.produck.ticket_mapper import ticket_from_mcp_result
from app.models.produck import ProduckTicket
from pathlib import Path

logger = logging.getLogger(__name__)


class ProduckTicketFetcher:
    def __init__(
        self,
        connector: ProduckMcpConnector,
        output_dir: Path,
        groq: GroqIncidentAnalyzer | None = None,
        search_domain: str | None = None,
        max_tickets_per_poll: int = 1,
    ):
        self.connector = connector
        self.output_dir = output_dir
        self.groq = groq
        self.search_domain = search_domain
        self.max_tickets_per_poll = max(1, max_tickets_per_poll)

    async def list_tools(self) -> list[dict[str, Any]]:
        return await self.connector.list_tools()

    async def fetch_ticket(
        self,
        feedback_id: str,
        tool_name: str | None = None,
        raw_args: dict[str, Any] | None = None,
    ) -> ProduckTicket:
        tools = await self.list_tools()
        tool = self._select_tool(tools, "fetch_feedback", tool_name)
        args = raw_args or self._build_arguments(tool, feedback_id)
        logger.info("Calling Produck feedback tool", extra={"tool_name": tool["name"]})
        raw = await self.connector.call_tool(tool["name"], args)
        return ticket_from_mcp_result(raw, feedback_id, self.output_dir)

    async def fetch_recent_tickets(self, feedback_ids: tuple[str, ...]) -> list[ProduckTicket]:
        return await self.fetch_open_tickets(feedback_ids)

    async def fetch_open_tickets(self, fallback_feedback_ids: tuple[str, ...] = ()) -> list[ProduckTicket]:
        summaries = await self.fetch_open_ticket_summaries(fallback_feedback_ids)
        ids = tuple(summary["feedback_id"] for summary in summaries)
        return await self._fetch_tickets_best_effort(ids)

    async def fetch_open_ticket_summaries(
        self,
        fallback_feedback_ids: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        tools = await self.list_tools()
        list_tool = self._select_tool(tools, "list_feedback", None, required=False)
        if list_tool is None:
            return [{"feedback_id": feedback_id, "status": "open"} for feedback_id in fallback_feedback_ids][
                : self.max_tickets_per_poll
            ]
        summaries = await self._search_open_feedback(list_tool)
        if not summaries and fallback_feedback_ids:
            summaries = [{"feedback_id": feedback_id, "status": "open"} for feedback_id in fallback_feedback_ids]
        return summaries[: self.max_tickets_per_poll]

    async def _fetch_tickets_best_effort(self, feedback_ids: tuple[str, ...]) -> list[ProduckTicket]:
        tickets: list[ProduckTicket] = []
        for feedback_id in feedback_ids:
            try:
                tickets.append(await self.fetch_ticket(feedback_id))
            except Exception as exc:
                logger.exception("Produck full ticket fetch failed", extra={"feedback_id": feedback_id})
                continue
        return tickets

    async def _search_open_feedback(self, tool: dict[str, Any]) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        cursor: str | None = None
        seen: set[str] = set()
        for _page in range(20):
            args = self._build_search_arguments(tool, cursor)
            raw = await self.connector.call_tool(tool["name"], args)
            page_summaries, cursor = self._extract_feedback_summaries(raw)
            for summary in page_summaries:
                feedback_id = summary["feedback_id"]
                if feedback_id not in seen:
                    seen.add(feedback_id)
                    summaries.append(summary)
            if not cursor:
                break
        return summaries

    async def close_ticket(self, ticket_id: str, note: str = "Resolved by LangGraph agent") -> dict[str, Any] | None:
        return await self.update_ticket_status(ticket_id, "resolved", note)

    async def update_ticket_status(
        self,
        ticket_id: str,
        status: str,
        note: str = "",
    ) -> dict[str, Any] | None:
        tools = await self.list_tools()
        tool = self._select_tool(tools, "close_feedback", None, required=False)
        if tool is None:
            return None
        args = self._build_arguments(tool, ticket_id)
        properties = (tool.get("inputSchema") or {}).get("properties", {})
        if note and "note" in properties:
            args["note"] = note
        for key in ("status", "state", "newStatus", "new_status"):
            if key in properties:
                args[key] = status
                break
        return await self.connector.call_tool(tool["name"], args)

    def _select_tool(
        self,
        tools: list[dict[str, Any]],
        purpose: str,
        requested: str | None,
        required: bool = True,
    ) -> dict[str, Any] | None:
        if requested:
            match = next((tool for tool in tools if tool.get("name") == requested), None)
            if match:
                return match
        names = [tool.get("name", "") for tool in tools]
        preferred_by_purpose = {
            "fetch_feedback": ("get_feedback", "get_feedback_report", "feedback_report", "read_feedback", "get_ticket"),
            "list_feedback": (
                "search_feedback",
                "list_feedback",
                "list_feedback_reports",
                "feedback_list",
                "list_tickets",
                "tickets",
            ),
            "close_feedback": (
                "update_feedback_status",
                "update_feedback",
                "set_feedback_status",
                "resolve_feedback",
                "close_feedback",
                "update_ticket",
                "close_ticket",
            ),
        }
        for candidate in preferred_by_purpose[purpose]:
            if candidate in names:
                return next(tool for tool in tools if tool.get("name") == candidate)
        purpose_word = "feedback" if "feedback" in purpose else "ticket"
        for tool in tools:
            name = str(tool.get("name", "")).lower()
            if purpose_word in name:
                if purpose.startswith("list") and ("list" in name or "recent" in name):
                    return tool
                if purpose.startswith("close") and any(word in name for word in ("close", "resolve", "update")):
                    return tool
                if purpose.startswith("fetch") and not any(word in name for word in ("list", "close", "resolve")):
                    return tool
        if self.groq:
            chooser = getattr(self.groq, "choose_produck_tool", None)
            if callable(chooser):
                choice = chooser(tools, purpose)
                match = next((tool for tool in tools if tool.get("name") == choice), None)
                if match:
                    return match
        if required:
            raise RuntimeError(f"Could not choose a Produck MCP tool for {purpose}. Available: {', '.join(names)}")
        return None

    @staticmethod
    def _build_arguments(tool: dict[str, Any], feedback_id: str) -> dict[str, Any]:
        schema = tool.get("inputSchema") or {}
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        required = schema.get("required", []) if isinstance(schema, dict) else []
        for key in ("feedbackId", "feedback_id", "id", "ticketId", "ticket_id", "reportId", "report_id"):
            if key in properties or key in required:
                return {key: feedback_id}
        return {"feedbackId": feedback_id}

    def _build_search_arguments(self, tool: dict[str, Any], cursor: str | None) -> dict[str, Any]:
        schema = tool.get("inputSchema") or {}
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        args: dict[str, Any] = {}
        if "limit" in properties:
            args["limit"] = 50
        if cursor and "cursor" in properties:
            args["cursor"] = cursor
        if self.search_domain and "domain" in properties:
            args["domain"] = self.search_domain
        for key in ("status", "state"):
            if key in properties:
                args[key] = "open"
                break
        return args

    @staticmethod
    def _extract_feedback_ids(raw: dict[str, Any]) -> tuple[str, ...]:
        found: list[str] = []

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key.lower() in {"feedbackid", "feedback_id", "ticketid", "ticket_id", "id"}:
                        if isinstance(item, str) and item:
                            found.append(item)
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(raw)
        return tuple(dict.fromkeys(found))

    @classmethod
    def _extract_feedback_summaries(cls, raw: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        payloads = cls._structured_payloads(raw)
        summaries: list[dict[str, Any]] = []
        next_cursor: str | None = None
        for payload in payloads:
            items: Any
            if isinstance(payload, dict) and isinstance(payload.get("items"), list):
                items = payload["items"]
                if isinstance(payload.get("nextCursor"), str):
                    next_cursor = payload["nextCursor"] or None
            elif isinstance(payload, list):
                items = payload
            else:
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                feedback_id = item.get("feedbackId") or item.get("feedback_id") or item.get("id")
                if not isinstance(feedback_id, str) or not feedback_id:
                    continue
                if cls._is_closed_or_ignored(item):
                    continue
                summaries.append(
                    {
                        "feedback_id": feedback_id,
                        "page_url": item.get("pageUrl") or item.get("page_url"),
                        "created_at": item.get("createdAt") or item.get("created_at"),
                        "summary": item.get("firstAnnotationText") or item.get("summary") or item.get("title"),
                        "status": item.get("status") or item.get("state") or "open",
                    }
                )
        return summaries, next_cursor

    @staticmethod
    def _structured_payloads(raw: dict[str, Any]) -> list[Any]:
        payloads: list[Any] = []
        structured = raw.get("structuredContent")
        if structured is not None:
            payloads.append(structured)
        for block in raw.get("content", []):
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = str(block.get("text", "")).strip()
            if not text or text[0] not in "[{":
                continue
            try:
                payloads.append(json.loads(text))
            except json.JSONDecodeError:
                continue
        return payloads or [raw]

    @staticmethod
    def _is_closed_or_ignored(item: dict[str, Any]) -> bool:
        if item.get("isSpam") is True:
            return True
        status = str(item.get("status") or item.get("state") or "").strip().lower()
        if not status:
            return False
        return status not in {"open", "new", "todo", "to_do"}
