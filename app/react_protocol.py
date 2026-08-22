from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


class ReActParseError(ValueError):
    """模型输出不符合 ReAct 协议。"""


@dataclass(frozen=True, slots=True)
class ReActResponse:
    thought: str
    action: str
    action_input: str

    @property
    def is_finish(self) -> bool:
        return self.action.casefold() == "finish"


_THOUGHT_RE = re.compile(r"(?:^|\n)\s*Thought\s*:\s*(.*?)(?=\n\s*Action\s*:)", re.I | re.S)
_ACTION_RE = re.compile(r"(?:^|\n)\s*Action\s*:\s*([A-Za-z_][\w-]*)\s*\[([\s\S]*)\]\s*$", re.I)
_FINISH_RE = re.compile(r"(?:^|\n)\s*Finish\s*:\s*([\s\S]+)$", re.I)


def parse_react_response(content: str) -> ReActResponse:
    """解析 Thought/Action 文本，动作输入允许包含换行和嵌套方括号。"""
    text = (content or "").strip()
    thought_match = _THOUGHT_RE.search(text)
    action_match = _ACTION_RE.search(text)
    if action_match:
        thought = thought_match.group(1).strip() if thought_match else "执行下一步动作。"
        return ReActResponse(
            thought=thought,
            action=action_match.group(1).strip(),
            action_input=action_match.group(2).strip(),
        )
    finish_match = _FINISH_RE.search(text)
    if finish_match:
        return ReActResponse(
            thought=thought_match.group(1).strip() if thought_match else "已有足够信息。",
            action="Finish",
            action_input=finish_match.group(1).strip(),
        )
    raise ReActParseError("响应必须包含 Action: Tool[input] 或 Action: Finish[answer]")


ACTION_ALIASES = {
    "search": "web_search",
    "weather": "get_weather",
    "calculate": "calculate",
    "time": "get_current_time",
    "ptc": "execute_ptc",
}

DISPLAY_NAMES = {
    "web_search": "Search",
    "get_weather": "Weather",
    "calculate": "Calculate",
    "get_current_time": "Time",
    "execute_ptc": "PTC",
}


def resolve_action_name(action: str, available_names: set[str], ptc_name: str) -> str:
    """把面向模型的简短动作别名转换为项目真实工具名。"""
    normalized = action.casefold()
    resolved = ACTION_ALIASES.get(normalized, action)
    if resolved == "execute_ptc":
        return ptc_name
    by_casefold = {name.casefold(): name for name in available_names}
    actual = by_casefold.get(resolved.casefold())
    if not actual:
        allowed = ", ".join(sorted((*available_names, ptc_name)))
        raise ValueError(f"未知动作 {action}；可用动作：{allowed}")
    return actual


def parse_action_arguments(tool_name: str, raw_input: str, ptc_name: str) -> dict[str, Any]:
    """将 ReAct 方括号中的文本规范化为 Registry/PTC 参数对象。"""
    value = raw_input.strip()
    if tool_name == "web_search" and not value.startswith("{"):
        return {"query": value}
    if tool_name == "get_weather" and not value.startswith("{"):
        return {"location": value}
    if tool_name == "get_current_time" and not value.startswith("{"):
        return {"time_zone": value or "Asia/Shanghai"}
    if tool_name == ptc_name and not value.startswith("{"):
        return {"code": value}
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"动作参数必须是 JSON 对象：{exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("动作参数必须是 JSON 对象")
    return parsed


def build_tool_descriptions(definitions: list[dict[str, Any]], ptc_definition: dict[str, Any]) -> str:
    """把 JSON function 定义压缩为可注入 ReAct 系统提示词的工具目录。"""
    rows: list[str] = []
    for definition in [*definitions, ptc_definition]:
        function = definition["function"]
        name = function["name"]
        display = DISPLAY_NAMES.get(name, name)
        schema = json.dumps(function.get("parameters", {}), ensure_ascii=False, separators=(",", ":"))
        rows.append(f"- {display}（真实名称 {name}）：{function.get('description', '')} 参数 Schema：{schema}")
    return "\n".join(rows)


def display_action_name(tool_name: str) -> str:
    return DISPLAY_NAMES.get(tool_name, tool_name)
