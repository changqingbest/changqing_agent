from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.logging_config import log_event


logger = logging.getLogger(__name__)


# Provider 是 Agent Loop 与具体模型厂商之间的适配层。
# 上层只需要 complete(messages, tools)，不需要了解 URL、Bearer 鉴权和 HTTP 细节。
class OpenAICompatibleProvider:
    # 参数：api_key 为鉴权密钥；base_url 为兼容接口根地址；model 为模型标识。
    # 副作用：无网络请求，仅把启动配置保存到实例字段。
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        enable_search: bool = False,
        search_strategy: str = "turbo",
        forced_search: bool = False,
    ) -> None:
        # 密钥只能用于请求头，调用方不得把本字段输出到日志或前端。
        self.api_key = api_key
        # 去掉末尾斜杠，避免拼接后产生 //chat/completions。
        self.base_url = base_url.rstrip("/")
        # 每次请求都会把该值放进请求体的 model 字段。
        self.model = model
        # 千问 OpenAI 兼容接口通过非标准顶层字段 enable_search 开启原生联网搜索。
        self.enable_search = enable_search
        # 官方支持 turbo（速度/效果平衡）和 max（更全面但更慢）两种通用策略。
        if search_strategy not in {"turbo", "max"}:
            raise ValueError("search_strategy 必须是 turbo 或 max")
        self.search_strategy = search_strategy
        # False 时由模型判断是否联网；True 用于强时效场景，要求每轮都执行搜索。
        self.forced_search = forced_search

    # 返回：没有 API Key 时为 True，表示使用本地演示分支且不产生网络费用。
    @property
    def is_demo(self) -> bool:
        return not self.api_key

    def _build_payload(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """构造请求体；仅启用时加入千问专有搜索字段。"""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.4,
        }
        # ReAct 文本模式会把动作目录注入系统上下文并传入空列表；此时不能继续发送
        # tool_choice=auto，否则部分 OpenAI 兼容服务会因为没有 tools 而拒绝请求。
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if self.enable_search:
            payload["enable_search"] = True
            payload["search_options"] = {
                "search_strategy": self.search_strategy,
                "forced_search": self.forced_search,
            }
        return payload

    # 作用：发送一次 OpenAI Chat Completions 兼容请求，返回 assistant 消息对象。
    # messages：完整上下文，包含 system/user/assistant/tool 等角色消息。
    # tools：模型可选择的函数工具定义，格式遵循 OpenAI function tools 协议。
    # 返回：choices[0].message，可能是最终文本，也可能包含 tool_calls。
    # 异常：网络失败由 httpx 抛出；HTTP 错误或响应结构异常转为 RuntimeError。
    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        # 演示模式仍模拟标准 assistant 消息，使网页和 Agent Loop 可离线联调。
        if self.is_demo:
            # 从后往前寻找最后一条用户消息；极端情况下没有用户消息则使用“你好”。
            user_message = next(
                (item for item in reversed(messages) if item.get("role") == "user"),
                {"content": "你好"},
            )
            answer = f"演示模式已收到：{user_message['content']}\n\n配置 API Key 后会切换到真实模型。"
            is_react = any(
                item.get("role") == "system" and "【ReAct 输出协议】" in str(item.get("content", ""))
                for item in messages
            )
            reply = {
                "role": "assistant",
                "content": (
                    f"Thought: 当前是演示模式，直接说明运行状态。\nAction: Finish[{answer}]"
                    if is_react
                    else answer
                ),
            }
            log_event(
                logger,
                logging.INFO,
                "model.demo.completed",
                "演示模式已生成本地回复",
                model=self.model,
                message_count=len(messages),
                answer_chars=len(answer),
            )
            return reply

        # 请求体只放模型推理所需字段。tool_choice=auto 允许模型自行决定是否调用工具。
        payload = self._build_payload(messages, tools)
        # 百炼兼容接口和 OpenAI 接口都接受 Bearer Token；不要打印本字典。
        headers = {"Authorization": f"Bearer {self.api_key}"}
        started = time.perf_counter()
        endpoint_host = urlparse(self.base_url).hostname
        log_event(
            logger,
            logging.INFO,
            "model.request.started",
            "开始调用模型服务",
            model=self.model,
            endpoint_host=endpoint_host,
            message_count=len(messages),
            tool_count=len(tools),
            native_search=self.enable_search,
            search_strategy=self.search_strategy if self.enable_search else None,
            forced_search=self.forced_search if self.enable_search else False,
        )

        # 为每次调用创建并自动关闭异步客户端。90 秒覆盖普通模型推理与工具规划耗时。
        # 基础版本优先清晰；高并发场景可把 client 提升为长生命周期连接池。
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
        except httpx.HTTPError:
            log_event(
                logger,
                logging.ERROR,
                "model.request.network_error",
                "模型服务网络请求失败",
                exc_info=True,
                model=self.model,
                endpoint_host=endpoint_host,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise

        # 非 2xx/3xx 响应不能继续当作模型消息解析。
        if response.is_error:
            log_event(
                logger,
                logging.ERROR,
                "model.request.http_error",
                "模型服务返回错误状态",
                model=self.model,
                endpoint_host=endpoint_host,
                status_code=response.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                upstream_request_id=response.headers.get("x-request-id"),
            )
            # 不把上游响应正文带进异常和日志；部分服务会在错误正文中回显请求内容。
            request_id = response.headers.get("x-request-id") or "unknown"
            raise RuntimeError(
                f"模型请求失败 ({response.status_code})，上游 request_id={request_id}"
            )

        # Chat Completions 的正常答案位于 choices[0].message。
        # 使用安全 get 链避免缺字段时先抛出难懂的 KeyError/IndexError。
        try:
            response_payload = response.json()
        except ValueError as exc:
            log_event(
                logger,
                logging.ERROR,
                "model.response.invalid_json",
                "模型服务返回了无效 JSON",
                model=self.model,
                status_code=response.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                response_bytes=len(response.content),
            )
            raise RuntimeError("模型响应不是有效 JSON") from exc
        choices = response_payload.get("choices") or []
        message = choices[0].get("message") if choices else None
        # 空 message 表示供应商响应不符合当前协议，必须中止本轮 Agent Loop。
        if not message:
            log_event(
                logger,
                logging.ERROR,
                "model.response.invalid",
                "模型响应缺少 message 字段",
                model=self.model,
                status_code=response.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise RuntimeError("模型响应中没有 message")
        usage = response_payload.get("usage") or {}
        log_event(
            logger,
            logging.INFO,
            "model.request.completed",
            "模型服务调用完成",
            model=self.model,
            endpoint_host=endpoint_host,
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            upstream_request_id=(
                response_payload.get("request_id")
                or response.headers.get("x-request-id")
                or response_payload.get("id")
            ),
            prompt_tokens=usage.get("prompt_tokens") or usage.get("input_tokens"),
            completion_tokens=usage.get("completion_tokens") or usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
            tool_call_count=len(message.get("tool_calls") or []),
            answer_chars=len(message.get("content") or ""),
        )
        return message
