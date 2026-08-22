import unittest

from app.agent import AgentLoop
from app.prompt_manager import PromptManager, get_interpreter_catalog
from app.ptc import PTCExecutor
from app.react_protocol import parse_action_arguments, parse_react_response, resolve_action_name
from app.tools import create_default_registry


class PromptManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = PromptManager()

    def test_selects_research_for_current_product_question(self) -> None:
        selected = self.manager.select("华为最新发布的手机型号和主要卖点是什么？")
        self.assertEqual(selected.id, "research")

    def test_selects_coding_and_injects_protocol(self) -> None:
        selected = self.manager.select("请诊断这段 Python 代码为什么报错")
        prompt = self.manager.build_system_prompt(
            base_prompt="test",
            template=selected,
            runtime_now="2026-08-22T12:00:00+08:00",
            runtime_weekday="星期六",
            tool_descriptions="- Search: 搜索",
        )
        self.assertEqual(selected.id, "coding")
        self.assertIn("编程诊断解释器", prompt)
        self.assertIn("2026-08-22T12:00:00+08:00（Asia/Shanghai，星期六）", prompt)
        self.assertIn("Action: Finish", prompt)
        self.assertIn("Observation", prompt)

    def test_interpreter_catalog_has_general_fallback(self) -> None:
        catalog = get_interpreter_catalog()
        ids = [item["id"] for item in catalog["templates"]]
        self.assertIn("general", ids)
        self.assertEqual(len(ids), len(set(ids)))


class ReActProtocolTests(unittest.TestCase):
    def test_parses_compact_search_action(self) -> None:
        response = parse_react_response(
            "Thought: 需要搜索当前发布信息。\nAction: Search[华为最新手机型号及主要卖点]"
        )
        self.assertEqual(response.thought, "需要搜索当前发布信息。")
        self.assertEqual(response.action, "Search")
        self.assertEqual(response.action_input, "华为最新手机型号及主要卖点")

    def test_action_alias_and_natural_language_input_are_normalized(self) -> None:
        tools = create_default_registry()
        name = resolve_action_name("Search", tools.names(), "execute_ptc")
        arguments = parse_action_arguments(name, "华为最新手机", "execute_ptc")
        self.assertEqual(name, "web_search")
        self.assertEqual(arguments, {"query": "华为最新手机"})

    def test_finish_keeps_multiline_answer(self) -> None:
        response = parse_react_response("Thought: 信息充分。\nAction: Finish[第一行\n第二行]")
        self.assertTrue(response.is_finish)
        self.assertEqual(response.action_input, "第一行\n第二行")


class _TextReActProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.last_messages = []
        self.received_tools = []

    async def complete(self, messages, tools):
        self.calls += 1
        self.received_tools.append(tools)
        if self.calls == 1:
            return {
                "role": "assistant",
                "content": (
                    "Thought: 需要先计算得到准确结果。\n"
                    'Action: Calculate[{"operation":"add","left":20,"right":22}]'
                ),
            }
        self.last_messages = messages
        return {
            "role": "assistant",
            "content": "Thought: 计算观察已经足够。\nAction: Finish[结果是 42。]",
        }


class TextReActAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_react_runs_thought_action_observation_finish(self) -> None:
        tools = create_default_registry()
        provider = _TextReActProvider()
        events = []
        agent = AgentLoop(
            provider=provider,
            tools=tools,
            ptc=PTCExecutor(tools),
            system_prompt="test",
        )

        answer = await agent.run([{"role": "user", "content": "请计算 20 加 22"}], events.append)

        self.assertEqual(answer, "结果是 42。")
        self.assertEqual(provider.calls, 2)
        self.assertTrue(all(item == [] for item in provider.received_tools))
        self.assertEqual(provider.last_messages[-1]["role"], "user")
        self.assertIn("Observation (Calculate)", provider.last_messages[-1]["content"])
        self.assertIn('"result": 42', provider.last_messages[-1]["content"])
        event_types = [event["type"] for event in events]
        self.assertIn("interpreter", event_types)
        self.assertIn("thought", event_types)
        self.assertIn("action", event_types)
        self.assertIn("observation", event_types)
        self.assertEqual(next(event for event in events if event["type"] == "interpreter")["id"], "data")


if __name__ == "__main__":
    unittest.main()
