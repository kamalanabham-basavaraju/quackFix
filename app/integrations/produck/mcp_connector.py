from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.integrations.produck.ticket_mapper import to_jsonable

logger = logging.getLogger(__name__)


class ProduckError(RuntimeError):
    """Raised when Produck MCP operations fail."""


class ProduckMcpConnector:
    def __init__(self, url: str, token: str | None, timeout: float = 60, retries: int = 2):
        self.url = url
        self.token = token
        self.timeout = timeout
        self.retries = retries

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise ProduckError("PRODUCK_MCP_TOKEN is required for Produck MCP calls")
        return {"Authorization": f"Bearer {self.token}"}

    async def list_tools(self) -> list[dict[str, Any]]:
        async def operation() -> list[dict[str, Any]]:
            try:
                from mcp import ClientSession
                from mcp.client.streamable_http import streamablehttp_client
            except ImportError as exc:
                raise ProduckError("The MCP SDK is not installed. Run `pip install mcp`.") from exc
            async with streamablehttp_client(self.url, headers=self._headers()) as (read, write, _session_id):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await asyncio.wait_for(session.list_tools(), timeout=self.timeout)
                    return [self._tool_to_dict(tool) for tool in result.tools]

        return await self._with_retry("list_tools", operation)

    async def call_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        async def operation() -> dict[str, Any]:
            try:
                from mcp import ClientSession
                from mcp.client.streamable_http import streamablehttp_client
            except ImportError as exc:
                raise ProduckError("The MCP SDK is not installed. Run `pip install mcp`.") from exc
            async with streamablehttp_client(self.url, headers=self._headers()) as (read, write, _session_id):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await asyncio.wait_for(session.call_tool(tool_name, args), timeout=self.timeout)
                    payload = to_jsonable(result)
                    if not isinstance(payload, dict):
                        raise ProduckError(f"Produck MCP tool {tool_name} returned unsupported payload")
                    return payload

        return await self._with_retry(f"call_tool:{tool_name}", operation)

    async def _with_retry(self, label: str, operation):
        delay = 1.0
        last_error: BaseException | None = None
        for attempt in range(self.retries + 1):
            try:
                return await operation()
            except Exception as exc:  # MCP transports use several exception classes.
                last_error = exc
                if attempt >= self.retries:
                    break
                logger.warning(
                    "Produck MCP call failed, retrying",
                    extra={
                        "operation": label,
                        "attempt": attempt + 1,
                        "error": self._summarize_error(exc),
                    },
                )
                await asyncio.sleep(delay)
                delay *= 2
        raise ProduckError(f"Produck MCP {label} failed: {self._summarize_error(last_error)}") from last_error

    @staticmethod
    def _tool_to_dict(tool: Any) -> dict[str, Any]:
        return {
            "name": getattr(tool, "name", ""),
            "description": getattr(tool, "description", "") or "",
            "inputSchema": to_jsonable(getattr(tool, "inputSchema", {}) or {}),
        }

    @classmethod
    def _summarize_error(cls, error: BaseException | None) -> str:
        if error is None:
            return "unknown error"
        if isinstance(error, BaseExceptionGroup):
            return "; ".join(cls._summarize_error(item) for item in error.exceptions)
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code:
            return f"{type(error).__name__}: HTTP {status_code}"
        return f"{type(error).__name__}: {error}"
