from __future__ import annotations

from typing import Any

import httpx


class OpenAICompatibleProvider:
    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    @property
    def is_demo(self) -> bool:
        return not self.api_key

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if self.is_demo:
            user_message = next(
                (item for item in reversed(messages) if item.get("role") == "user"),
                {"content": "你好"},
            )
            return {
                "role": "assistant",
                "content": f"演示模式已收到：{user_message['content']}\n\n配置 API Key 后会切换到真实模型。",
            }

        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.4,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )

        if response.is_error:
            detail = response.text[:500]
            raise RuntimeError(f"模型请求失败 ({response.status_code})：{detail}")

        message = response.json().get("choices", [{}])[0].get("message")
        if not message:
            raise RuntimeError("模型响应中没有 message")
        return message
