import asyncio

from app.agent import AgentLoop
from app.config import settings
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.ptc import PTCExecutor
from app.tools import create_default_registry


# 该脚本执行“真实模型 + PTC + 两个工具”的连通性检查，不启动网页服务。
# 运行方式：python -m scripts.verify_model。它会产生一次或多次真实模型调用费用。

# 作用：组装一套独立 Agent，要求模型通过 PTC 完成固定任务，并打印可人工检查的事件链。
# 返回：无。失败通过异常或 SystemExit 体现，使命令行退出码可用于自动化检查。
async def main() -> None:
    # 演示模式无法证明外部模型连通，因此缺少密钥时立即以非成功状态退出。
    if settings.is_demo:
        raise SystemExit("未检测到 DASHSCOPE_API_KEY 或 OPENAI_API_KEY。")

    # 使用与 Web 服务相同的默认工具集合，但实例独立，验证不会修改服务进程状态。
    tools = create_default_registry()
    # 按发生顺序保存精简事件标签，最终用于确认模型是否真的经过工具调用阶段。
    events: list[str] = []

    # 事件回调：记录所有事件；tool_end 额外打印完整结果以便定位 PTC 语法或工具错误。
    # 参数 event：AgentLoop 产生的事件字典。返回值：无；副作用：追加列表并可能打印控制台。
    def record_event(event: dict) -> None:
        # tool_start 后拼接工具名，其余事件只记录类型，使最终链路紧凑易读。
        label = f"{event['type']}:{event.get('name')}" if event["type"] == "tool_start" else event["type"]
        events.append(label)
        # 打印结果不会包含 Provider API Key，但新增工具后仍应注意其业务结果是否敏感。
        if event["type"] == "tool_end":
            print(f"Tool result ({event.get('name')}): {event.get('result')}")
    # 手工注入 Provider、Registry 和 PTC，验证的正是生产 AgentLoop 的依赖组合方式。
    agent = AgentLoop(
        provider=OpenAICompatibleProvider(
            api_key=settings.api_key,
            base_url=settings.base_url,
            model=settings.model,
        ),
        tools=tools,
        ptc=PTCExecutor(tools),
        # 强制优先 PTC，避免模型直接凭自身知识回答“6×7”而绕过待测链路。
        system_prompt="你是连通性检查助手。必须调用工具，并优先使用 execute_ptc。",
        max_steps=8,
    )
    # 一个任务同时需要时间与计算，适合观察 execute_ptc 是否在一次程序内组合多个工具。
    answer = await agent.run(
        [{"role": "user", "content": "用 PTC 获取上海当前时间并计算 6 乘以 7，然后一句话回答。"}],
        record_event,
    )
    # 下列输出刻意不打印 api_key；Provider/Model/Events/Answer 足以确认接入结果。
    print(f"Provider: {settings.provider_name}")
    print(f"Model: {settings.model}")
    print(f"Events: {' -> '.join(events)}")
    print(f"Answer: {answer}")


# 只在模块作为命令运行时创建事件循环；被测试代码导入时不会自动产生模型费用。
if __name__ == "__main__":
    asyncio.run(main())
