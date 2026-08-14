import asyncio

from app.agent import AgentLoop
from app.config import settings
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.ptc import PTCExecutor
from app.tools import create_default_registry


async def main() -> None:
    if settings.is_demo:
        raise SystemExit("未检测到 DASHSCOPE_API_KEY 或 OPENAI_API_KEY。")

    tools = create_default_registry()
    events: list[str] = []

    def record_event(event: dict) -> None:
        label = f"{event['type']}:{event.get('name')}" if event["type"] == "tool_start" else event["type"]
        events.append(label)
        if event["type"] == "tool_end":
            print(f"Tool result ({event.get('name')}): {event.get('result')}")
    agent = AgentLoop(
        provider=OpenAICompatibleProvider(
            api_key=settings.api_key,
            base_url=settings.base_url,
            model=settings.model,
        ),
        tools=tools,
        ptc=PTCExecutor(tools),
        system_prompt="你是连通性检查助手。必须调用工具，并优先使用 execute_ptc。",
        max_steps=8,
    )
    answer = await agent.run(
        [{"role": "user", "content": "用 PTC 获取上海当前时间并计算 6 乘以 7，然后一句话回答。"}],
        record_event,
    )
    print(f"Provider: {settings.provider_name}")
    print(f"Model: {settings.model}")
    print(f"Events: {' -> '.join(events)}")
    print(f"Answer: {answer}")


if __name__ == "__main__":
    asyncio.run(main())
