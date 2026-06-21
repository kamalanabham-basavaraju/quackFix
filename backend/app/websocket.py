from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)

    async def connect(self, execution_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[execution_id].append(websocket)

    def disconnect(self, execution_id: str, websocket: WebSocket) -> None:
        if websocket in self._connections.get(execution_id, []):
            self._connections[execution_id].remove(websocket)

    async def broadcast(self, execution_id: str, payload: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for websocket in self._connections.get(execution_id, []):
            try:
                await websocket.send_json(payload)
            except RuntimeError:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(execution_id, websocket)


manager = ConnectionManager()
