import unittest

from app.providers.openai_compatible import OpenAICompatibleProvider


class ProviderNativeSearchTests(unittest.TestCase):
    def test_qwen_search_fields_are_added_to_chat_payload(self) -> None:
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen-plus",
            enable_search=True,
            search_strategy="max",
            forced_search=True,
        )

        payload = provider._build_payload([{"role": "user", "content": "今天的新闻"}], [])

        self.assertTrue(payload["enable_search"])
        self.assertEqual(payload["search_options"]["search_strategy"], "max")
        self.assertTrue(payload["search_options"]["forced_search"])

    def test_non_qwen_payload_omits_proprietary_search_fields(self) -> None:
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="test-model",
        )

        payload = provider._build_payload([{"role": "user", "content": "hello"}], [])

        self.assertNotIn("enable_search", payload)
        self.assertNotIn("search_options", payload)

    def test_search_strategy_is_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "turbo 或 max"):
            OpenAICompatibleProvider(
                api_key="test-key",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                model="qwen-plus",
                enable_search=True,
                search_strategy="agent",
            )

    def test_react_payload_omits_native_tool_fields_when_catalog_is_empty(self) -> None:
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="test-model",
        )

        payload = provider._build_payload([{"role": "user", "content": "hello"}], [])

        self.assertNotIn("tools", payload)
        self.assertNotIn("tool_choice", payload)


if __name__ == "__main__":
    unittest.main()
