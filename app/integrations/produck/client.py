from __future__ import annotations

from pathlib import Path
from typing import Any

from app.integrations.groq import GroqIncidentAnalyzer
from app.integrations.produck.mcp_connector import ProduckError, ProduckMcpConnector
from app.integrations.produck.ticket_fetcher import ProduckTicketFetcher
from app.models.produck import ProduckTicket


class ProduckClient:
    def __init__(
        self,
        url: str,
        token: str | None,
        output_dir: Path,
        timeout: float = 60,
        groq: GroqIncidentAnalyzer | None = None,
        search_domain: str | None = None,
        max_tickets_per_poll: int = 1,
    ):
        self.connector = ProduckMcpConnector(url, token, timeout=timeout)
        self.fetcher = ProduckTicketFetcher(
            self.connector,
            output_dir,
            groq=groq,
            search_domain=search_domain,
            max_tickets_per_poll=max_tickets_per_poll,
        )

    async def list_tools(self) -> list[dict[str, Any]]:
        return await self.fetcher.list_tools()

    async def fetch_ticket(
        self,
        feedback_id: str,
        tool_name: str | None = None,
        args: dict[str, Any] | None = None,
    ) -> ProduckTicket:
        return await self.fetcher.fetch_ticket(feedback_id, tool_name, args)

    async def fetch_recent_tickets(self, feedback_ids: tuple[str, ...]) -> list[ProduckTicket]:
        return await self.fetcher.fetch_recent_tickets(feedback_ids)

    async def fetch_open_tickets(self, fallback_feedback_ids: tuple[str, ...] = ()) -> list[ProduckTicket]:
        return await self.fetcher.fetch_open_tickets(fallback_feedback_ids)

    async def fetch_open_ticket_summaries(
        self,
        fallback_feedback_ids: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        return await self.fetcher.fetch_open_ticket_summaries(fallback_feedback_ids)

    async def close_ticket(self, ticket_id: str, note: str = "Resolved by LangGraph agent") -> dict[str, Any] | None:
        return await self.fetcher.close_ticket(ticket_id, note)

    async def update_ticket_status(
        self,
        ticket_id: str,
        status: str,
        note: str = "",
    ) -> dict[str, Any] | None:
        return await self.fetcher.update_ticket_status(ticket_id, status, note)
