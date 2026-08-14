const DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1";

export function resolveModelConfig(env = process.env) {
  // 显式的通用配置优先，便于以后无缝切换其他 OpenAI 兼容服务。
  if (env.OPENAI_API_KEY) {
    return {
      apiKey: env.OPENAI_API_KEY,
      baseUrl: env.OPENAI_BASE_URL || "https://api.openai.com/v1",
      model: env.OPENAI_MODEL || "gpt-4.1-mini",
      providerName: "OpenAI Compatible",
    };
  }

  // 本机已配置百炼密钥时，无需复制密钥或创建 .env，自动接入千问。
  if (env.DASHSCOPE_API_KEY) {
    return {
      apiKey: env.DASHSCOPE_API_KEY,
      baseUrl: env.DASHSCOPE_BASE_URL || DASHSCOPE_BASE_URL,
      model: env.QWEN_MODEL || "qwen-plus",
      providerName: "Qwen / DashScope",
    };
  }

  return {
    apiKey: "",
    baseUrl: env.OPENAI_BASE_URL || DASHSCOPE_BASE_URL,
    model: env.QWEN_MODEL || env.OPENAI_MODEL || "qwen-plus",
    providerName: "Demo",
  };
}
