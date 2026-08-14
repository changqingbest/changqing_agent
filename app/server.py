from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent import AgentLoop
from app.config import PROJECT_ROOT, settings
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.ptc import PTCExecutor
from app.store import ConversationStore
from app.tools import create_default_registry


class ChatRequest(BaseModel):
    conversationId: str
    message: str = Field(min_length=1, max_length=12_000)


tools = create_default_registry()
ptc = PTCExecutor(tools)
provider = OpenAICompatibleProvider(
    api_key=settings.api_key,
    base_url=settings.base_url,
    model=settings.model,
)
agent = AgentLoop(
    provider=provider,
    tools=tools,
    ptc=ptc,
    system_prompt=settings.system_prompt,
)
store = ConversationStore(PROJECT_ROOT / "data" / "conversations.json")
app = FastAPI(title="Changqing Agent", version="0.2.0")


@app.get("/api/status")
async def status() -> dict[str, Any]:
    return {
        "mode": "demo" if provider.is_demo else "model",
        "model": provider.model,
        "provider": settings.provider_name,
        "ptc": True,
        "port": settings.port,
    }


@app.get("/api/conversations")
async def list_conversations() -> list[dict[str, Any]]:
    return await store.list()


@app.post("/api/conversations", status_code=201)
async def create_conversation() -> dict[str, Any]:
    return await store.create()


@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: str) -> dict[str, Any]:
    conversation = await store.get(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str) -> dict[str, bool]:
    if not await store.delete(conversation_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


@app.post("/api/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空")
    try:
        conversation = await store.add_message(request.conversationId, "user", message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def event_stream():
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def run_agent() -> None:
            try:
                answer = await agent.run(conversation["messages"], queue.put_nowait)
                await store.add_message(request.conversationId, "assistant", answer)
                await queue.put({"type": "done"})
            except Exception as exc:
                await queue.put({"type": "error", "value": str(exc)})
            finally:
                await queue.put(None)

        task = asyncio.create_task(run_agent())
        try:
            while (event := await queue.get()) is not None:
                yield _sse(event)
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    return StreamingResponse(event_stream(), media_type="text/event-stream")


app.mount("/", StaticFiles(directory=Path(PROJECT_ROOT / "public"), html=True), name="web")
