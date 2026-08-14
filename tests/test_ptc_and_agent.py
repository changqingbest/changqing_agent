import json
import unittest

from app.agent import AgentLoop
from app.ptc import PTCExecutor
from app.ptc.executor import PTCError
from app.tools import create_default_registry


# 测试分为两层：PTCExecutorTests 验证语法白名单，AgentLoopTests 验证模型与工具的循环协议。
# 所有测试都使用本地函数或假 Provider，不访问网络，也不会消耗真实模型额度。

# PTC 单元测试使用同步 TestCase，因为 PTC 解释器和内置示例工具都是同步执行。
class PTCExecutorTests(unittest.TestCase):
    # 每个用例前创建全新 Registry/PTC，避免变量、调用记录或未来可变状态在测试间泄漏。
    def setUp(self) -> None:
        # tools 字段：包含时间和计算工具的默认注册表。
        self.tools = create_default_registry()
        # ptc 字段：本用例专用的受限解释器，共用上面的注册表。
        self.ptc = PTCExecutor(self.tools)

    # 正向用例：一段 PTC 程序应能顺序调用两个工具，并通过 emit 汇总结果。
    def test_program_can_compose_multiple_tools(self) -> None:
        result = self.ptc.execute(
            "time = get_current_time(time_zone='Asia/Shanghai')\n"
            "math = calculate(operation='multiply', left=6, right=7)\n"
            "emit({'time': time['value'], 'answer': math['result']})"
        )
        # output 验证模型可见最终值，tool_calls 验证底层确实执行了两个真实工具。
        self.assertEqual(result["output"][0]["answer"], 42)
        self.assertEqual([item["name"] for item in result["tool_calls"]], ["get_current_time", "calculate"])

    # 安全反向用例：import 必须在语句白名单入口处被拒绝。
    def test_import_is_rejected(self) -> None:
        with self.assertRaisesRegex(PTCError, "Import"):
            self.ptc.execute("import os")

    # 安全反向用例：字符串方法也是 Attribute 调用，不能借此触达任意对象能力。
    def test_attribute_access_is_rejected(self) -> None:
        with self.assertRaisesRegex(PTCError, "Attribute"):
            self.ptc.execute("emit('x'.upper())")

    # 兼容性用例：允许最基础 f-string 汇总工具结果，减少模型因 JoinedStr 反复重试。
    def test_f_string_can_format_tool_results(self) -> None:
        result = self.ptc.execute(
            "math = calculate(operation='multiply', left=6, right=7)\n"
            "emit(f\"answer={math['result']}\")"
        )
        self.assertEqual(result["output"], ["answer=42"])


# 最小假 Provider：第一次要求 execute_ptc，第二次读取工具结果并给出最终文本。
# 以下划线开头表示它仅供本测试模块内部使用，不是生产 Provider。
class _FakeProvider:
    # calls 记录 complete 被调用次数，用来验证 Agent 是否真的进入第二轮推理。
    def __init__(self) -> None:
        self.calls = 0

    # 参数签名故意与真实 Provider 一致，AgentLoop 因此无需测试专用分支。
    # 返回：第一次为 tool_calls 消息，后续为普通 assistant 文本。
    async def complete(self, messages, tools):
        self.calls += 1
        # 第一次模拟模型选择 PTC，并传入 JSON 字符串形式的 arguments。
        if self.calls == 1:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "execute_ptc",
                            "arguments": json.dumps(
                                {"code": "value = calculate(operation='add', left=20, right=22)\nemit(value)"}
                            ),
                        },
                    }
                ],
            }
        # 保存第二轮完整上下文，供测试断言 role=tool 的结果已正确回注。
        self.last_messages = messages
        return {"role": "assistant", "content": "结果是 42。"}


# IsolatedAsyncioTestCase 为每个异步测试创建隔离事件循环，避免协程状态相互影响。
class AgentLoopTests(unittest.IsolatedAsyncioTestCase):
    # 端到端单元用例：假模型发起 PTC → 框架执行 → 工具结果回注 → 模型最终回答。
    async def test_agent_loops_after_ptc_result(self) -> None:
        # 以下字段都是本用例局部依赖，不读取真实 settings 或 API Key。
        tools = create_default_registry()
        provider = _FakeProvider()
        # events 收集 EventHandler 字典，验证生命周期中确实出现 tool_start。
        events = []
        agent = AgentLoop(
            provider=provider,
            tools=tools,
            ptc=PTCExecutor(tools),
            system_prompt="test",
        )
        # list.append 符合 EventHandler 签名，是测试中最简单的事件收集器。
        answer = await agent.run([{"role": "user", "content": "计算"}], events.append)

        # 最终文本、模型轮数、消息协议、工具结果和事件流分别验证不同责任边界。
        self.assertEqual(answer, "结果是 42。")
        self.assertEqual(provider.calls, 2)
        self.assertEqual(provider.last_messages[-1]["role"], "tool")
        self.assertIn('"result": 42', provider.last_messages[-1]["content"])
        self.assertIn("tool_start", [event["type"] for event in events])


# 支持直接运行本文件；常规项目命令仍推荐 python -m unittest discover -s tests -v。
if __name__ == "__main__":
    unittest.main()
