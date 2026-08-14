from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from app.ptc import PTCExecutor
from app.tools import ToolRegistry


EventHandler = Callable[[dict[str, Any]], None]


class AgentLoop:
    def __init__(
        self,
        *,
        provider: Any,
        tools: ToolRegistry,
        ptc: PTCExecutor,
        system_prompt: str,
        max_steps: int = 8,
    ) -> None:
        self.provider = provider
        self.tools = tools
        self.ptc = ptc
        self.system_prompt = system_prompt
        self.max_steps = max_steps

    async def run(
        self, history: list[dict[str, Any]], on_event: EventHandler = lambda _event: None
    ) -> str:
        messages = [
            {"role": "system", "content": self.system_prompt},
            *({"role": item["role"], "content": item["content"]} for item in history),
        ]
        definitions = [*self.tools.definitions(), self.ptc.definition()]

        for step in range(self.max_steps):
            on_event({"type": "status", "value": "thinking" if step == 0 else "working"})
            reply = await self.provider.complete(messages, definitions)
            tool_calls = reply.get("tool_calls") or []
            if not tool_calls:
                answer = reply.get("content") or "模型没有返回文本。"
                on_event({"type": "answer", "value": answer})
                return answer

            messages.append(reply)
            for call in tool_calls:
                function = call.get("function", {})
                name = function.get("name", "")
                arguments = function.get("arguments", "{}")
                on_event({"type": "tool_start", "name": name})
                try:
                    if name == self.ptc.TOOL_NAME:
                        parsed = json.loads(arguments or "{}")
                        result = self.ptc.execute(parsed.get("code", ""))
                    else:
                        result = self.tools.call(name, arguments)
                except Exception as exc:  # 工具错误作为结果返回，让模型有机会自行修正。
                    result = {"error": str(exc)}
                on_event({"type": "tool_end", "name": name, "result": result})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )

        raise RuntimeError(f"Agent 超过最大执行步数：{self.max_steps}")
