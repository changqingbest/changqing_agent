import json
import unittest

import app.server as server
from app.providers.openai_compatible import OpenAICompatibleProvider


class RuntimeModelConfigTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original_provider = server.agent.provider
        self.original_provider_name = server.runtime_provider_name
        server.agent.provider = OpenAICompatibleProvider(
            api_key="existing-secret",
            base_url="https://old.example/v1",
            model="old-model",
        )
        server.runtime_provider_name = "Old Provider"

    def tearDown(self) -> None:
        server.agent.provider = self.original_provider
        server.runtime_provider_name = self.original_provider_name

    async def test_runtime_switch_keeps_existing_key_when_field_is_omitted(self) -> None:
        request = server.ModelConfigRequest(
            provider_name="Custom Provider",
            base_url="https://new.example/v1/chat/completions",
            model="new-model",
        )

        result = await server.update_model_config(request)

        self.assertEqual(server.agent.provider.api_key, "existing-secret")
        self.assertEqual(server.agent.provider.base_url, "https://new.example/v1")
        self.assertEqual(server.agent.provider.model, "new-model")
        self.assertEqual(result["provider_name"], "Custom Provider")
        self.assertTrue(result["api_key_configured"])
        self.assertEqual(result["source"], "runtime")

    async def test_runtime_switch_never_returns_submitted_api_key(self) -> None:
        secret = "never-return-this-secret"
        request = server.ModelConfigRequest(
            provider_name="Qwen / DashScope",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen-plus",
            api_key=secret,
            enable_search=True,
            search_strategy="max",
            forced_search=True,
        )

        result = await server.update_model_config(request)

        self.assertEqual(server.agent.provider.api_key, secret)
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn("api_key", result)
        self.assertTrue(result["api_key_configured"])
        self.assertTrue(result["enable_search"])
        self.assertEqual(result["search_strategy"], "max")
        self.assertTrue(result["forced_search"])

    async def test_native_search_rejects_non_qwen_endpoint(self) -> None:
        request = server.ModelConfigRequest(
            provider_name="Other Provider",
            base_url="https://models.example/v1",
            model="other-model",
            enable_search=True,
        )

        with self.assertRaisesRegex(server.HTTPException, "只能用于百炼"):
            await server.update_model_config(request)


if __name__ == "__main__":
    unittest.main()
