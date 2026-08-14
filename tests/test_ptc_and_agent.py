import json
import unittest

from app.agent import AgentLoop
from app.ptc import PTCExecutor
from app.ptc.executor import PTCError
from app.tools import create_default_registry


class PTCExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tools = create_default_registry()
        self.ptc = PTCExecutor(self.tools)

    def test_program_can_compose_multiple_tools(self) -> None:
        result = self.ptc.execute(
            "time = get_current_time(time_zone='Asia/Shanghai')\n"
            "math = calculate(operation='multiply', left=6, right=7)\n"
            "emit({'time': time['value'], 'answer': math['result']})"
        )
        self.assertEqual(result["output"][0]["answer"], 42)
        self.assertEqual([item["name"] for item in result["tool_calls"]], ["get_current_time", "calculate"])

    def test_import_is_rejected(self) -> None:
        with self.assertRaisesRegex(PTCError, "Import"):
            self.ptc.execute("import os")

    def test_attribute_access_is_rejected(self) -> None:
        with self.assertRaisesRegex(PTCError, "Attribute"):
            self.ptc.execute("emit('x'.upper())")

    def test_f_string_can_format_tool_results(self) -> None:
        result = self.ptc.execute(
            "math = calculate(operation='multiply', left=6, right=7)\n"
            "emit(f\"answer={math['result']}\")"
        )
        self.assertEqual(result["output"], ["answer=42"])


class _FakeProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages, tools):
        self.calls += 1
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
        self.last_messages = messages
        return {"role": "assistant", "content": "结果是 42。"}


class AgentLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_loops_after_ptc_result(self) -> None:
        tools = create_default_registry()
        provider = _FakeProvider()
        events = []
        agent = AgentLoop(
            provider=provider,
            tools=tools,
            ptc=PTCExecutor(tools),
            system_prompt="test",
        )
        answer = await agent.run([{"role": "user", "content": "计算"}], events.append)

        self.assertEqual(answer, "结果是 42。")
        self.assertEqual(provider.calls, 2)
        self.assertEqual(provider.last_messages[-1]["role"], "tool")
        self.assertIn('"result": 42', provider.last_messages[-1]["content"])
        self.assertIn("tool_start", [event["type"] for event in events])


if __name__ == "__main__":
    unittest.main()
