from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo


ToolHandler = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def as_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具已注册：{tool.name}")
        self._tools[tool.name] = tool

    def names(self) -> set[str]:
        return set(self._tools)

    def definitions(self) -> list[dict[str, Any]]:
        return [tool.as_openai_tool() for tool in self._tools.values()]

    def call(self, name: str, arguments: str | dict[str, Any] | None) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"未注册的工具：{name}")
        if isinstance(arguments, str):
            kwargs = json.loads(arguments or "{}")
        else:
            kwargs = arguments or {}
        if not isinstance(kwargs, dict):
            raise ValueError("工具参数必须是 JSON 对象")
        return tool.handler(**kwargs)


def _get_current_time(time_zone: str = "Asia/Shanghai") -> dict[str, str]:
    now = datetime.now(ZoneInfo(time_zone))
    return {"time_zone": time_zone, "value": now.isoformat(timespec="seconds")}


def _calculate(operation: str, left: float, right: float) -> dict[str, float | str]:
    operations: dict[str, Callable[[float, float], float]] = {
        "add": lambda a, b: a + b,
        "subtract": lambda a, b: a - b,
        "multiply": lambda a, b: a * b,
        "divide": lambda a, b: a / b,
    }
    if operation not in operations:
        raise ValueError(f"不支持的运算：{operation}")
    return {"operation": operation, "result": operations[operation](left, right)}


def create_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="get_current_time",
            description="获取指定 IANA 时区的当前时间。",
            parameters={
                "type": "object",
                "properties": {
                    "time_zone": {
                        "type": "string",
                        "description": "例如 Asia/Shanghai",
                    }
                },
                "additionalProperties": False,
            },
            handler=_get_current_time,
        )
    )
    registry.register(
        Tool(
            name="calculate",
            description="执行两个数字的基础运算。",
            parameters={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["add", "subtract", "multiply", "divide"],
                    },
                    "left": {"type": "number"},
                    "right": {"type": "number"},
                },
                "required": ["operation", "left", "right"],
                "additionalProperties": False,
            },
            handler=_calculate,
        )
    )
    return registry
