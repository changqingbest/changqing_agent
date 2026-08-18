from __future__ import annotations

from typing import Any

import httpx


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
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.4,
        }
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
            return {
                "role": "assistant",
                "content": f"演示模式已收到：{user_message['content']}\n\n配置 API Key 后会切换到真实模型。",
            }

        # 请求体只放模型推理所需字段。tool_choice=auto 允许模型自行决定是否调用工具。
        payload = self._build_payload(messages, tools)
        # 百炼兼容接口和 OpenAI 接口都接受 Bearer Token；不要打印本字典。
        headers = {"Authorization": f"Bearer {self.api_key}"}

        # 为每次调用创建并自动关闭异步客户端。90 秒覆盖普通模型推理与工具规划耗时。
        # 基础版本优先清晰；高并发场景可把 client 提升为长生命周期连接池。
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )

        # 非 2xx/3xx 响应不能继续当作模型消息解析。
        if response.is_error:
            # 只截取前 500 个字符，避免上游超长错误页灌满日志或 SSE 响应。
            detail = response.text[:500]
            raise RuntimeError(f"模型请求失败 ({response.status_code})：{detail}")

        # Chat Completions 的正常答案位于 choices[0].message。
        # 使用安全 get 链避免缺字段时先抛出难懂的 KeyError/IndexError。
        message = response.json().get("choices", [{}])[0].get("message")
        # 空 message 表示供应商响应不符合当前协议，必须中止本轮 Agent Loop。
        if not message:
            raise RuntimeError("模型响应中没有 message")
        return message
