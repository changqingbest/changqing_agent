import { Agent } from "../src/agent/agent.js";
import { OpenAICompatibleProvider } from "../src/agent/provider.js";
import { resolveModelConfig } from "../src/config.js";

const config = resolveModelConfig();
if (!config.apiKey) {
  console.error("未检测到 DASHSCOPE_API_KEY 或 OPENAI_API_KEY。");
  process.exitCode = 1;
} else {
  console.log(`Provider: ${config.providerName}`);
  console.log(`Model: ${config.model}`);

  const agent = new Agent({
    provider: new OpenAICompatibleProvider(config),
    systemPrompt: "你是模型连通性检查助手。必须按用户要求调用可用工具。",
    maxSteps: 4,
  });

  const events = [];
  const answer = await agent.run(
    [{ role: "user", content: "调用工具获取 Asia/Shanghai 当前时间，然后用一句中文回答。" }],
    (event) => events.push(event.type === "tool_start" ? `${event.type}:${event.name}` : event.type),
  );

  console.log(`Events: ${events.join(" -> ")}`);
  console.log(`Answer: ${answer}`);
}
