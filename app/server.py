from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AnyHttpUrl, BaseModel, Field

from app.agent import AgentLoop
from app.config import PROJECT_ROOT, settings
from app.prompts import get_prompt_catalog
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.ptc import PTCExecutor
from app.store import ConversationStore
from app.tools import create_default_registry


# 本文件是“传输层/组装层”：把配置、模型、工具、PTC、存储和 Agent Loop 连接起来，
# 并通过 FastAPI 暴露 REST + SSE 接口。核心推理逻辑仍在 app/agent.py，避免与 Web 框架耦合。

# POST /api/chat 的请求体模型。Pydantic 会在进入路由函数前完成基本类型和长度校验。
class ChatRequest(BaseModel):
    # 前端当前选中的会话 UUID。沿用前端 camelCase 字段，避免额外映射配置。
    conversationId: str
    # 用户消息正文：至少一个字符，最多 12000 字符；路由内还会拒绝纯空白文本。
    message: str = Field(min_length=1, max_length=12_000)


class ModelConfigRequest(BaseModel):
    # 展示名称只用于前端状态区，不参与网络路由。
    provider_name: str = Field(min_length=1, max_length=64)
    # 支持 OpenAI Chat Completions 协议的服务根地址，可为云服务或本地服务。
    base_url: AnyHttpUrl
    # 模型标识由目标服务定义，例如 qwen-plus；不在本地维护易过期的白名单。
    model: str = Field(min_length=1, max_length=128)
    # 不回显现有密钥。省略或只传空白表示保留当前进程中的密钥。
    api_key: str | None = Field(default=None, max_length=2048)
    # 千问原生联网搜索是 Chat Completions 的非标准扩展，只对百炼兼容端点发送。
    enable_search: bool = False
    # turbo 平衡速度与效果，max 使用更全面的检索策略。
    search_strategy: str = Field(default="turbo", pattern="^(turbo|max)$")
    # False 由模型判断是否搜索；True 每轮请求都强制搜索。
    forced_search: bool = False


def _is_qwen_compatible_endpoint(base_url: str) -> bool:
    """识别百炼 OpenAI 兼容端点，避免把专有字段发给其他服务。"""
    parsed = urlparse(base_url)
    hostname = (parsed.hostname or "").lower()
    return hostname.endswith("aliyuncs.com") and "/compatible-mode/v1" in parsed.path


# 以下对象都是进程级单例，在模块导入（应用启动）时组装一次。
# 它们保存配置和无会话状态的服务对象，可被多个请求复用。

# 默认工具目录，包含时间、计算、联网搜索和天气查询。
tools = create_default_registry(tavily_api_key=settings.tavily_api_key)
# PTC 与普通 Agent 调用共享同一个 tools，保证工具定义和真实执行函数一致。
ptc = PTCExecutor(tools)
# Provider 只接收模型相关配置；api_key 不会通过状态接口返回。
provider = OpenAICompatibleProvider(
    api_key=settings.api_key,
    base_url=settings.base_url,
    model=settings.model,
    enable_search=_is_qwen_compatible_endpoint(settings.base_url),
)
# 展示名称与 Provider 一起作为运行时配置；API Key 始终只保留在 Provider 内存字段中。
runtime_provider_name = settings.provider_name
# 切换锁保证两个同时提交的设置请求不会交错覆盖。
model_config_lock = asyncio.Lock()
# Agent Loop 注入依赖，不自行创建 Provider/Registry，便于测试和后续替换实现。
agent = AgentLoop(
    provider=provider,
    tools=tools,
    ptc=ptc,
    system_prompt=settings.system_prompt,
)
# 会话保存到项目 data 目录；该 JSON 文件已被 .gitignore 排除。
store = ConversationStore(PROJECT_ROOT / "data" / "conversations.json")
# FastAPI 应用对象是 uvicorn 的加载入口 app.server:app。
app = FastAPI(title="Changqing Agent", version="0.8.0")


# 本地工作台的 HTML/JS/CSS 会频繁更新。明确禁止浏览器缓存这些入口资源，
# 避免服务已更新但旧标签页刷新后仍显示上一版本的界面。
@app.middleware("http")
async def disable_frontend_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in {"/", "/index.html", "/app.js", "/styles.css", "/changqing-logo.svg"}:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


# GET /api/status
# 作用：向网页报告运行模式和展示信息，用于左下角连接状态。
# 返回值不含 API Key、base_url 或系统提示词，避免敏感配置泄漏到浏览器。
@app.get("/api/status")
async def status() -> dict[str, Any]:
    current_provider = agent.provider
    return {
        # mode 让前端区分本地演示回复与真实模型连接。
        "mode": "demo" if current_provider.is_demo else "model",
        "model": current_provider.model,
        "provider": runtime_provider_name,
        # ptc=True 表示本进程已经挂载程序化工具调用层，不代表任意代码执行已开放。
        "ptc": True,
        "tools": sorted(tools.names()),
        "search_provider": "tavily" if settings.tavily_api_key else "bing_rss",
        "qwen_native_search": current_provider.enable_search,
        "port": settings.port,
    }


def _public_model_config() -> dict[str, Any]:
    """返回可公开的运行时模型配置，明确排除 API Key。"""
    current_provider = agent.provider
    return {
        "provider_name": runtime_provider_name,
        "base_url": current_provider.base_url,
        "model": current_provider.model,
        "api_key_configured": not current_provider.is_demo,
        "enable_search": current_provider.enable_search,
        "search_strategy": current_provider.search_strategy,
        "forced_search": current_provider.forced_search,
        "source": "environment" if current_provider is provider else "runtime",
    }


@app.get("/api/model-config")
async def get_model_config() -> dict[str, Any]:
    return _public_model_config()


@app.post("/api/model-config")
async def update_model_config(request: ModelConfigRequest) -> dict[str, Any]:
    """在当前进程内切换 OpenAI 兼容模型，不持久化或回显密钥。"""
    global runtime_provider_name

    provider_name = request.provider_name.strip()
    model = request.model.strip()
    if not provider_name or not model:
        raise HTTPException(status_code=400, detail="供应商名称和模型名称不能为空")

    base_url = str(request.base_url).rstrip("/")
    # 用户常会粘贴完整 Chat Completions 地址；统一还原为 Provider 所需根地址。
    suffix = "/chat/completions"
    if base_url.endswith(suffix):
        base_url = base_url[: -len(suffix)]
    if request.enable_search and not _is_qwen_compatible_endpoint(base_url):
        raise HTTPException(
            status_code=400,
            detail="千问原生联网搜索只能用于百炼 OpenAI 兼容端点",
        )

    async with model_config_lock:
        current_provider = agent.provider
        submitted_key = (request.api_key or "").strip()
        api_key = submitted_key or current_provider.api_key
        next_provider = OpenAICompatibleProvider(
            api_key=api_key,
            base_url=base_url,
            model=model,
            enable_search=request.enable_search,
            search_strategy=request.search_strategy,
            forced_search=request.forced_search,
        )
        # 单次对象赋值是切换边界；AgentLoop.run 会在每轮开始时捕获该对象快照。
        agent.provider = next_provider
        runtime_provider_name = provider_name

    return _public_model_config()


# GET /api/prompt-templates
# 返回项目内置的提示词分类和模板。模板是只读静态内容，不包含密钥或用户会话数据。
@app.get("/api/prompt-templates")
async def prompt_templates() -> dict[str, Any]:
    return get_prompt_catalog()


# GET /api/conversations
# 返回左侧任务列表摘要，不返回全部消息正文，减少初次加载的数据量。
@app.get("/api/conversations")
async def list_conversations() -> list[dict[str, Any]]:
    return await store.list()


# POST /api/conversations
# 创建一个空任务。201 表示服务器成功创建了新资源。
@app.post("/api/conversations", status_code=201)
async def create_conversation() -> dict[str, Any]:
    return await store.create()


# GET /api/conversations/{conversation_id}
# 参数来自 URL 路径；返回完整会话和消息，供用户切换任务时恢复聊天记录。
@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: str) -> dict[str, Any]:
    conversation = await store.get(conversation_id)
    # 用 HTTP 404 明确表达资源不存在，而不是返回空对象让前端误判。
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation


# DELETE /api/conversations/{conversation_id}
# 物理删除整个会话。Store 返回 False 时转换为标准 404。
@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str) -> dict[str, bool]:
    if not await store.delete(conversation_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


# 作用：把内部事件字典编码为 Server-Sent Events 的单条 data 消息。
# SSE 规定一条事件以空行结束，所以字符串末尾必须是两个换行符。
# ensure_ascii=False 保留中文；default=str 兜底处理时间等非 JSON 原生对象。
def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


# POST /api/chat
# 作用：持久化用户消息、后台运行 Agent，并把生命周期事件以 SSE 持续返回。
# 返回：StreamingResponse；连接期间可能依次收到 status、tool_start、tool_end、answer、done。
@app.post("/api/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    # 去掉首尾空白，既避免标题含无意义空格，也补充 Pydantic 长度校验遗漏的纯空白情况。
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空")
    try:
        # 必须先保存 user 消息，再把更新后的历史交给 Agent，确保模型能看到本轮输入。
        conversation = await store.add_message(request.conversationId, "user", message)
    except KeyError as exc:
        # Store 保持与 HTTP 无关，由本层负责把领域错误翻译成 404。
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # 异步生成器是 SSE 的数据源。每次 yield 一条事件，FastAPI 就可立即写给浏览器。
    # 该函数每个请求创建一份独立队列和任务，不会与其他会话混用事件。
    async def event_stream():
        # None 是内部结束哨兵，不会被编码或发送到前端。
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        # 后台协程负责运行可能耗时的模型循环；队列把它与 SSE 消费速度解耦。
        async def run_agent() -> None:
            try:
                # put_nowait 是轻量同步回调，符合 AgentLoop 的 EventHandler 接口。
                answer = await agent.run(conversation["messages"], queue.put_nowait)
                # 只有得到最终答案后才保存 assistant 消息，工具中间事件不进入长期会话文件。
                await store.add_message(request.conversationId, "assistant", answer)
                # done 告诉网页本轮完整成功，前端可解除输入框禁用状态。
                await queue.put({"type": "done"})
            except Exception as exc:
                # 模型、存储或循环的未处理异常转为 SSE error，避免连接无说明地断开。
                # 基础版本直接返回错误文本；生产环境应进行日志记录和敏感信息脱敏。
                await queue.put({"type": "error", "value": str(exc)})
            finally:
                # 无论成功失败都放入结束哨兵，保证 event_stream 不会永久等待。
                await queue.put(None)

        # create_task 让 Agent 生产事件与当前生成器消费事件并发推进。
        task = asyncio.create_task(run_agent())
        try:
            # 每取到一个事件立即编码并 yield；收到 None 后正常结束 HTTP 流。
            while (event := await queue.get()) is not None:
                yield _sse(event)
        finally:
            # 浏览器中途断开时生成器会进入 finally；取消仍在运行的模型任务，避免无主工作。
            if not task.done():
                task.cancel()
                # 等待被取消任务收尾，同时只抑制预期的 CancelledError。
                with suppress(asyncio.CancelledError):
                    await task

    # media_type 告诉浏览器这是 text/event-stream；事件正文由 event_stream 按需生成。
    return StreamingResponse(event_stream(), media_type="text/event-stream")


# 静态站点挂载必须放在所有 /api 路由之后，因为“/”会匹配任意剩余路径。
# html=True 使根路径自动返回 public/index.html，从而复用原生前端而无需模板引擎。
app.mount("/", StaticFiles(directory=Path(PROJECT_ROOT / "public"), html=True), name="web")
