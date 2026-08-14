from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


class ConversationStore:
    def __init__(self, data_file: Path) -> None:
        self.data_file = data_file
        self._lock = asyncio.Lock()

    def _read(self) -> list[dict[str, Any]]:
        if not self.data_file.exists():
            return []
        return json.loads(self.data_file.read_text(encoding="utf-8"))

    def _write(self, items: list[dict[str, Any]]) -> None:
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.data_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.data_file)

    async def list(self) -> list[dict[str, Any]]:
        async with self._lock:
            items = self._read()
        summaries = [
            {
                "id": item["id"],
                "title": item["title"],
                "createdAt": item["createdAt"],
                "updatedAt": item["updatedAt"],
                "messageCount": len(item["messages"]),
            }
            for item in items
        ]
        return sorted(summaries, key=lambda item: item["updatedAt"], reverse=True)

    async def get(self, conversation_id: str) -> dict[str, Any] | None:
        async with self._lock:
            return next((item for item in self._read() if item["id"] == conversation_id), None)

    async def create(self) -> dict[str, Any]:
        async with self._lock:
            items = self._read()
            now = datetime.now(UTC).isoformat()
            conversation = {
                "id": str(uuid4()),
                "title": "新任务",
                "createdAt": now,
                "updatedAt": now,
                "messages": [],
            }
            items.append(conversation)
            self._write(items)
            return conversation

    async def add_message(self, conversation_id: str, role: str, content: str) -> dict[str, Any]:
        async with self._lock:
            items = self._read()
            conversation = next((item for item in items if item["id"] == conversation_id), None)
            if conversation is None:
                raise KeyError("会话不存在")
            conversation["messages"].append(
                {
                    "id": str(uuid4()),
                    "role": role,
                    "content": content,
                    "createdAt": datetime.now(UTC).isoformat(),
                }
            )
            if role == "user" and sum(m["role"] == "user" for m in conversation["messages"]) == 1:
                conversation["title"] = " ".join(content.split())[:28] or "新任务"
            conversation["updatedAt"] = datetime.now(UTC).isoformat()
            self._write(items)
            return conversation

    async def delete(self, conversation_id: str) -> bool:
        async with self._lock:
            items = self._read()
            remaining = [item for item in items if item["id"] != conversation_id]
            if len(remaining) == len(items):
                return False
            self._write(remaining)
            return True
