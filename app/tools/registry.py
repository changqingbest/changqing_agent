from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.logging_config import log_event


logger = logging.getLogger(__name__)


_WEEKDAYS_ZH = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


# 统一描述工具处理函数的类型：可接收任意命名参数并返回任意可序列化结果。
# 当前基础框架只调用同步函数；未来支持 async handler 时应在 Registry 边界统一 await。
ToolHandler = Callable[..., Any]


# Tool 把“给模型看的说明”和“本地真正执行的函数”绑定在一起。
# frozen=True 防止注册后被篡改；slots=True 固定字段并减少拼写错误。
@dataclass(frozen=True, slots=True)
class Tool:
    # 工具唯一名称，同时也是模型 tool_call 中 function.name 的匹配键。
    name: str
    # 面向模型的自然语言说明；描述越清晰，模型越容易在正确场景选择它。
    description: str
    # JSON Schema 参数定义，用于约束模型生成的 arguments 形状。
    parameters: dict[str, Any]
    # 真正执行业务动作的 Python 函数，不会被直接发送给模型。
    handler: ToolHandler

    # 作用：把内部 Tool 转换为 OpenAI 兼容接口接受的 function tool 结构。
    # 返回：全新字典；handler 不会进入网络请求，避免不可序列化和代码泄漏。
    def as_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ToolRegistry 是所有工具的唯一目录，负责注册、枚举、协议转换和调用分发。
# Agent Loop 与 PTCExecutor 都依赖它，因此两种调用方式始终使用同一批真实处理函数。
class ToolRegistry:
    # 初始化一个空注册表。键是工具名，值是不可变 Tool 描述对象。
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    # 作用：加入一个工具。
    # 参数 tool：已经包含名称、Schema 和 handler 的 Tool 实例。
    # 异常：名称重复时抛 ValueError，避免后注册工具静默覆盖前一个工具。
    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具已注册：{tool.name}")
        self._tools[tool.name] = tool
        log_event(
            logger,
            logging.DEBUG,
            "tool.registered",
            "工具已注册",
            tool=tool.name,
        )

    # 返回：当前所有工具名的集合副本。调用方修改集合不会影响内部字典。
    def names(self) -> set[str]:
        return set(self._tools)

    # 返回：可直接放进模型请求 tools 字段的定义列表。
    # 边界：列表只含协议元数据，不含 Python handler。
    def definitions(self) -> list[dict[str, Any]]:
        return [tool.as_openai_tool() for tool in self._tools.values()]

    # 作用：按名称查找工具、规范化参数并执行 handler。
    # arguments：可以是模型返回的 JSON 字符串，也可以是 PTC 传入的字典，None 视为空对象。
    # 返回：handler 原始返回值，由 Agent Loop 负责 JSON 序列化后交回模型。
    # 异常：未知工具、非法 JSON、非对象参数或 handler 自身错误都会向上抛出。
    def call(self, name: str, arguments: str | dict[str, Any] | None) -> Any:
        # get 而不是直接下标，是为了给未知名称提供更清楚的业务错误。
        tool = self._tools.get(name)
        if tool is None:
            log_event(
                logger,
                logging.WARNING,
                "tool.unknown",
                "请求了未注册工具",
                tool=name or "unknown",
            )
            raise ValueError(f"未注册的工具：{name}")
        # 标准模型 tool_calls 的 arguments 通常是 JSON 字符串，需要先解码。
        if isinstance(arguments, str):
            kwargs = json.loads(arguments or "{}")
        else:
            # PTC 层直接传字典；None 表示无参数工具。
            kwargs = arguments or {}
        # handler 通过 **kwargs 调用，所以顶层必须是对象，数组或标量都不合法。
        if not isinstance(kwargs, dict):
            raise ValueError("工具参数必须是 JSON 对象")
        # Python 会继续校验必填参数、未知参数和类型相关运行错误。
        started = time.perf_counter()
        log_event(
            logger,
            logging.INFO,
            "tool.handler.started",
            "开始执行工具处理函数",
            tool=name,
            argument_fields=sorted(kwargs),
        )
        try:
            result = tool.handler(**kwargs)
        except Exception as exc:
            expected_error = isinstance(exc, (TypeError, ValueError, RuntimeError))
            log_event(
                logger,
                logging.WARNING if expected_error else logging.ERROR,
                "tool.handler.failed",
                "工具处理函数执行失败",
                exc_info=not expected_error,
                tool=name,
                error_type=type(exc).__name__,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise
        log_event(
            logger,
            logging.INFO,
            "tool.handler.completed",
            "工具处理函数执行完成",
            tool=name,
            result_type=type(result).__name__,
            result_items=len(result) if isinstance(result, (dict, list, tuple)) else None,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return result


# 内置示例工具：获取指定 IANA 时区当前时间。
# time_zone：例如 Asia/Shanghai；无效名称会由 ZoneInfo 抛出异常。
# 返回：保留时区名及带 UTC 偏移的 ISO 时间，方便模型准确解释。
def _get_current_time(time_zone: str = "Asia/Shanghai") -> dict[str, str | int]:
    now = datetime.now(ZoneInfo(time_zone))
    # 星期必须由 datetime 计算后结构化返回，不能只给模型 ISO 字符串让它自行心算。
    # Python weekday() 使用星期一=0；isoweekday() 使用星期一=1、星期日=7。
    utc_offset = now.strftime("%z")
    formatted_offset = f"{utc_offset[:3]}:{utc_offset[3:]}" if utc_offset else ""
    return {
        "time_zone": time_zone,
        "date": now.date().isoformat(),
        "time": now.time().isoformat(timespec="seconds"),
        "weekday": _WEEKDAYS_ZH[now.weekday()],
        "weekday_iso": now.isoweekday(),
        "utc_offset": formatted_offset,
        "value": now.isoformat(timespec="seconds"),
    }


# 内置示例工具：对两个数字执行有限的基础运算。
# operation：add/subtract/multiply/divide；left、right 为左右操作数。
# 返回：运算名称和结果。边界：除数为零时保留 Python 的 ZeroDivisionError。
def _calculate(operation: str, left: float, right: float) -> dict[str, float | str]:
    # 白名单映射比 eval() 安全：模型只能选择这里明确列出的四种行为。
    operations: dict[str, Callable[[float, float], float]] = {
        "add": lambda a, b: a + b,
        "subtract": lambda a, b: a - b,
        "multiply": lambda a, b: a * b,
        "divide": lambda a, b: a / b,
    }
    # 即使模型参数 Schema 已给 enum，服务端仍必须防御人工或异常调用。
    if operation not in operations:
        raise ValueError(f"不支持的运算：{operation}")
    return {"operation": operation, "result": operations[operation](left, right)}


# 作用：创建项目启动时使用的默认工具集合。
# 返回：已经注册时间、计算、搜索和天气工具的新 Registry；每次调用互不共享可变字典。
# 扩展方式：新增 Tool 后继续 registry.register(...)，无需修改 Agent Loop。
def create_default_registry(*, tavily_api_key: str = "", http_client: Any = None) -> ToolRegistry:
    # 先创建空目录，再逐个注册，重复名保护会在这里立即生效。
    registry = ToolRegistry()
    # 时间工具的 Schema 允许省略 time_zone，此时 handler 使用上海默认值。
    registry.register(
        Tool(
            name="get_current_time",
            description="获取指定 IANA 时区的当前日期、时间、中文星期、ISO 星期序号和 UTC 偏移。",
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
    # 计算工具要求三个字段齐全，并禁止模型附带未声明参数。
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
    # 网络工具拆分在独立模块中，延迟导入可避免 registry 与 network 相互导入时形成环。
    from app.tools.network import create_network_tools

    for tool in create_network_tools(tavily_api_key=tavily_api_key, client=http_client):
        registry.register(tool)
    # 返回完整注册表，交给普通工具调用和 PTC 层共同使用。
    return registry
