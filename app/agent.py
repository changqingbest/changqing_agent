from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.logging_config import log_event
from app.prompt_manager import PromptManager, prompt_manager
from app.ptc import PTCExecutor
from app.react_protocol import (
    ReActParseError,
    build_tool_descriptions,
    display_action_name,
    parse_action_arguments,
    parse_react_response,
    resolve_action_name,
)
from app.tools import ToolRegistry


logger = logging.getLogger(__name__)
EventHandler = Callable[[dict[str, Any]], None]


class AgentLoop:
    """执行模型思考、动作、观察和结束回答组成的 ReAct 循环。"""

    def __init__(
        self,
        *,
        provider: Any,
        tools: ToolRegistry,
        ptc: PTCExecutor,
        system_prompt: str,
        max_steps: int = 8,
        prompts: PromptManager | None = None,
    ) -> None:
        self.provider = provider
        self.tools = tools
        self.ptc = ptc
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.prompts = prompts or prompt_manager

    @staticmethod
    def _last_user_text(history: list[dict[str, Any]]) -> str:
        return next(
            (str(item.get("content", "")) for item in reversed(history) if item.get("role") == "user"),
            "",
        )

    @staticmethod
    def _serialize_result(result: Any) -> str:
        return json.dumps(result, ensure_ascii=False, default=str)

    @classmethod
    def _observation_preview(cls, result: Any, limit: int = 6000) -> str:
        value = cls._serialize_result(result)
        if len(value) <= limit:
            return value
        return f"{value[:limit]}\n…（观察结果已截断，共 {len(value)} 个字符）"

    async def _execute_tool(
        self,
        *,
        name: str,
        arguments: str | dict[str, Any],
        step: int,
        call_id: str | None,
        on_event: EventHandler,
    ) -> Any:
        """在线程中执行同步工具，并统一产生工具生命周期事件和日志。"""
        tool_started = time.perf_counter()
        log_event(
            logger,
            logging.INFO,
            "agent.tool.started",
            "ReAct 请求执行动作",
            step=step,
            tool=name or "unknown",
            argument_fields=sorted(arguments) if isinstance(arguments, dict) else None,
            argument_chars=len(arguments) if isinstance(arguments, str) else None,
            call_id=call_id,
        )
        on_event({"type": "tool_start", "name": display_action_name(name)})
        try:
            if name == self.ptc.TOOL_NAME:
                parsed = json.loads(arguments or "{}") if isinstance(arguments, str) else arguments
                if not isinstance(parsed, dict):
                    raise ValueError("PTC 参数必须是 JSON 对象")
                result = await asyncio.to_thread(self.ptc.execute, str(parsed.get("code", "")))
            else:
                result = await asyncio.to_thread(self.tools.call, name, arguments)
        except Exception as exc:
            result = {"error": str(exc)}
            log_event(
                logger,
                logging.WARNING,
                "agent.tool.failed",
                "ReAct 动作执行失败，观察结果将交回模型修正",
                exc_info=True,
                step=step,
                tool=name or "unknown",
                error_type=type(exc).__name__,
                duration_ms=round((time.perf_counter() - tool_started) * 1000, 2),
            )
        else:
            log_event(
                logger,
                logging.INFO,
                "agent.tool.completed",
                "ReAct 动作执行完成",
                step=step,
                tool=name or "unknown",
                result_type=type(result).__name__,
                duration_ms=round((time.perf_counter() - tool_started) * 1000, 2),
            )
        on_event({"type": "tool_end", "name": display_action_name(name), "result": result})
        on_event(
            {
                "type": "observation",
                "name": display_action_name(name),
                "value": self._observation_preview(result),
            }
        )
        return result

    async def _run_native_tool_calls(
        self,
        *,
        reply: dict[str, Any],
        messages: list[dict[str, Any]],
        step: int,
        on_event: EventHandler,
    ) -> None:
        """兼容仍返回原生 function tool_calls 的模型或自定义 Provider。"""
        messages.append(reply)
        for call in reply.get("tool_calls") or []:
            function = call.get("function", {})
            name = function.get("name", "")
            arguments = function.get("arguments", "{}")
            display_name = display_action_name(name)
            on_event({"type": "thought", "value": f"调用 {display_name} 获取完成任务所需的信息。"})
            on_event({"type": "action", "name": display_name, "input": arguments})
            result = await self._execute_tool(
                name=name,
                arguments=arguments,
                step=step,
                call_id=call.get("id"),
                on_event=on_event,
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "content": self._serialize_result(result),
                }
            )

    async def run(
        self,
        history: list[dict[str, Any]],
        on_event: EventHandler = lambda _event: None,
    ) -> str:
        """选择解释器并运行一轮最多 ``max_steps`` 步的 ReAct。"""
        runtime_now = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
        definitions = self.tools.definitions()
        ptc_definition = self.ptc.definition()
        user_text = self._last_user_text(history)
        interpreter = self.prompts.select(user_text)
        runtime_context = self.prompts.build_system_prompt(
            base_prompt=self.system_prompt,
            template=interpreter,
            runtime_now=runtime_now,
            tool_descriptions=build_tool_descriptions(definitions, ptc_definition),
        )
        messages = [
            {"role": "system", "content": runtime_context},
            *({"role": item["role"], "content": item["content"]} for item in history),
        ]
        on_event(
            {
                "type": "interpreter",
                "id": interpreter.id,
                "name": interpreter.name,
                "description": interpreter.description,
            }
        )

        provider = self.provider
        run_started = time.perf_counter()
        log_event(
            logger,
            logging.INFO,
            "agent.run.started",
            "ReAct Agent Loop 开始执行",
            model=getattr(provider, "model", "unknown"),
            interpreter=interpreter.id,
            history_messages=len(history),
            tool_count=len(definitions) + 1,
            max_steps=self.max_steps,
        )

        for step_index in range(self.max_steps):
            step = step_index + 1
            step_started = time.perf_counter()
            on_event({"type": "step", "value": step})
            on_event({"type": "status", "value": "thinking" if step == 1 else "working"})
            log_event(
                logger,
                logging.DEBUG,
                "agent.step.started",
                "ReAct 开始模型推理步骤",
                step=step,
                context_messages=len(messages),
            )

            # ReAct 的动作目录已经放在系统提示词中，因此正常模式不发送原生 tools。
            # 下方仍兼容 Provider 主动返回 tool_calls，便于迁移和接入旧模型。
            reply = await provider.complete(messages, [])
            if reply.get("tool_calls"):
                await self._run_native_tool_calls(
                    reply=reply,
                    messages=messages,
                    step=step,
                    on_event=on_event,
                )
                continue

            content = str(reply.get("content") or "").strip()
            try:
                react = parse_react_response(content)
            except ReActParseError as exc:
                # 兼容明确给出普通最终文本的模型；已经尝试 ReAct 却格式错误时要求重写。
                if "Thought:" not in content and "Action:" not in content and "Finish:" not in content:
                    answer = content or "模型没有返回文本。"
                    on_event({"type": "answer", "value": answer})
                    return answer
                observation = {"error": str(exc), "expected": "Thought + Action: Tool[input] 或 Finish[answer]"}
                on_event({"type": "observation", "name": "Protocol", "value": self._serialize_result(observation)})
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": f"Observation: {self._serialize_result(observation)}\n请严格按 ReAct 协议重写下一步。",
                    }
                )
                continue

            on_event({"type": "thought", "value": react.thought})
            if react.is_finish:
                answer = react.action_input or "模型没有返回最终答案。"
                on_event({"type": "action", "name": "Finish", "input": ""})
                on_event({"type": "answer", "value": answer})
                log_event(
                    logger,
                    logging.INFO,
                    "agent.run.completed",
                    "ReAct Agent Loop 已生成最终答案",
                    steps=step,
                    interpreter=interpreter.id,
                    answer_chars=len(answer),
                    duration_ms=round((time.perf_counter() - run_started) * 1000, 2),
                    step_duration_ms=round((time.perf_counter() - step_started) * 1000, 2),
                )
                return answer

            messages.append({"role": "assistant", "content": content})
            try:
                tool_name = resolve_action_name(react.action, self.tools.names(), self.ptc.TOOL_NAME)
                arguments = parse_action_arguments(tool_name, react.action_input, self.ptc.TOOL_NAME)
                action_name = display_action_name(tool_name)
                on_event({"type": "action", "name": action_name, "input": react.action_input})
                result = await self._execute_tool(
                    name=tool_name,
                    arguments=arguments,
                    step=step,
                    call_id=None,
                    on_event=on_event,
                )
            except Exception as exc:
                action_name = react.action
                result = {"error": str(exc)}
                on_event({"type": "action", "name": action_name, "input": react.action_input})
                on_event({"type": "observation", "name": action_name, "value": self._serialize_result(result)})

            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Observation ({action_name}): {self._serialize_result(result)}\n"
                        "请依据该观察继续下一步；信息充分时使用 Action: Finish[最终答案]。"
                    ),
                }
            )

        log_event(
            logger,
            logging.ERROR,
            "agent.run.step_limit",
            "ReAct Agent Loop 达到最大执行步数",
            max_steps=self.max_steps,
            interpreter=interpreter.id,
            duration_ms=round((time.perf_counter() - run_started) * 1000, 2),
        )
        raise RuntimeError(f"Agent 超过最大执行步数：{self.max_steps}")
