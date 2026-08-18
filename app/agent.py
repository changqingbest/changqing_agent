from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.ptc import PTCExecutor
from app.tools import ToolRegistry


# Agent Loop 是框架的“编排中心”，但它不直接实现模型 HTTP 请求或具体工具。
# 它只负责在模型消息、工具执行结果和最终答案之间循环，保持各层职责分离。

# 事件回调的统一类型：接收一个事件字典，不要求返回值。
# Web 层用它把 thinking/tool_start/tool_end/answer 等状态实时推送到 SSE 队列。
EventHandler = Callable[[dict[str, Any]], None]


# AgentLoop 管理一次用户请求从开始推理到最终回答的完整生命周期。
# 实例本身保存的是依赖和配置，不保存具体会话消息，因此可以被多个请求复用。
class AgentLoop:
    # provider：具有异步 complete(messages, tools) 方法的模型适配器。
    # tools：普通 JSON function calling 使用的工具注册表。
    # ptc：程序化工具调用执行器，与 tools 共用同一 Registry。
    # system_prompt：每轮请求最前面的系统指令；max_steps：模型往返次数上限。
    def __init__(
        self,
        *,
        provider: Any,
        tools: ToolRegistry,
        ptc: PTCExecutor,
        system_prompt: str,
        max_steps: int = 8,
    ) -> None:
        # Provider 使用 Any 是为了让核心循环不绑定某个 SDK，也方便测试注入假模型。
        self.provider = provider
        # 普通工具调用由 Registry 统一分发和校验参数。
        self.tools = tools
        # execute_ptc 调用由独立 PTCExecutor 解释，避免在循环中混入 AST 细节。
        self.ptc = ptc
        # 系统提示词只在 run() 组装消息时使用，不会写入会话持久化文件。
        self.system_prompt = system_prompt
        # 步数上限保护模型反复调用工具或反复修错造成的无限循环和费用失控。
        self.max_steps = max_steps

    # 作用：根据历史消息运行一次完整 Agent 循环并返回最终文本。
    # history：持久化的 user/assistant 消息列表；本方法不会原地修改它。
    # on_event：同步轻量回调，用于把生命周期事件交给 CLI 或 Web 层。
    # 返回：模型最终 assistant 文本。
    # 异常：Provider 失败或超过 max_steps 会向上抛出；单个工具错误则交回模型修正。
    async def run(
        self, history: list[dict[str, Any]], on_event: EventHandler = lambda _event: None
    ) -> str:
        # 为本轮创建新的模型上下文：系统消息只用于推理，不写回 history。
        # 这里只复制 role/content，避免把数据库中的 id、createdAt 等内部字段发给模型。
        runtime_now = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
        runtime_context = (
            f"{self.system_prompt}\n"
            f"当前可信运行时日期时间为 {runtime_now}（Asia/Shanghai）。"
            "联网问题必须以工具返回的标题、来源、链接和发布时间为依据；"
            "不要因为结果年份晚于模型训练数据就称其为模拟、测试或异常数据，"
            "也不要用记忆中的旧资讯替代搜索结果。"
        )
        messages = [
            {"role": "system", "content": runtime_context},
            *({"role": item["role"], "content": item["content"]} for item in history),
        ]
        # 模型同时看到普通工具和 execute_ptc，可按任务复杂度自行选择调用方式。
        definitions = [*self.tools.definitions(), self.ptc.definition()]
        # 一轮 Agent Loop 固定使用启动该轮时的 Provider 快照。
        # 前端即使在工具调用期间切换模型，也只会影响下一轮请求，不会让同一轮跨模型。
        provider = self.provider

        # 每轮最多产生一次模型请求；step=0 是首次思考，后续轮次处理工具结果。
        for step in range(self.max_steps):
            # 先发状态事件，使网页在等待模型网络响应期间能展示“正在思考”。
            on_event({"type": "status", "value": "thinking" if step == 0 else "working"})
            # Provider 返回兼容 message：可能包含 content，也可能包含一个或多个 tool_calls。
            reply = await provider.complete(messages, definitions)
            # 某些供应商用 null 或省略字段表示没有工具调用，统一转换为空列表。
            tool_calls = reply.get("tool_calls") or []
            # 没有工具调用意味着模型认为任务已经结束，应把文本作为最终答案返回。
            if not tool_calls:
                # content 为空时提供明确兜底文字，避免前端收到 null。
                answer = reply.get("content") or "模型没有返回文本。"
                on_event({"type": "answer", "value": answer})
                return answer

            # 工具结果前必须先保留包含 tool_calls 的 assistant 消息，协议顺序不能颠倒。
            messages.append(reply)
            # 同一条 assistant 消息可能要求并列调用多个工具，按返回顺序逐个执行。
            for call in tool_calls:
                # 使用 get 提供容错边界；结构残缺最终会转成工具错误交回模型。
                function = call.get("function", {})
                name = function.get("name", "")
                arguments = function.get("arguments", "{}")
                # 事件只暴露工具名，不向前端主动暴露密钥或完整模型上下文。
                on_event({"type": "tool_start", "name": name})
                try:
                    # execute_ptc 的参数外层仍是 JSON，其中 code 字段才是受限程序文本。
                    if name == self.ptc.TOOL_NAME:
                        parsed = json.loads(arguments or "{}")
                        result = await asyncio.to_thread(self.ptc.execute, parsed.get("code", ""))
                    else:
                        # 其他名称都走普通 Registry，包括未知名称的明确报错。
                        result = await asyncio.to_thread(self.tools.call, name, arguments)
                except Exception as exc:  # 工具错误作为结果返回，让模型有机会自行修正。
                    # 不让单次工具错误直接杀死 Agent：模型看到 error 后可修正参数或代码重试。
                    # 风险：生产环境应再区分可恢复业务错误与必须立即终止的系统错误。
                    result = {"error": str(exc)}
                # tool_end 用于网页观察和调试；结果可能较大，生产版应考虑截断或脱敏。
                on_event({"type": "tool_end", "name": name, "result": result})
                # 按协议把工具结果追加为 role=tool，并用原 call.id 建立对应关系。
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        # ensure_ascii=False 保留中文；default=str 给时间等非 JSON 类型提供兜底。
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )

        # 循环耗尽仍未得到最终文本时主动失败，避免静默返回不完整结果。
        raise RuntimeError(f"Agent 超过最大执行步数：{self.max_steps}")
