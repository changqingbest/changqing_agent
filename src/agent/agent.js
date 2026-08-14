import { executeTool, getToolDefinitions } from "./tools.js";

export class Agent {
  constructor({ provider, systemPrompt, maxSteps = 8 }) {
    this.provider = provider;
    this.systemPrompt = systemPrompt;
    this.maxSteps = maxSteps;
  }

  async run(history, onEvent = () => {}) {
    const messages = [
      { role: "system", content: this.systemPrompt },
      ...history.map(({ role, content }) => ({ role, content })),
    ];

    for (let step = 0; step < this.maxSteps; step += 1) {
      onEvent({ type: "status", value: step === 0 ? "thinking" : "working" });
      const reply = await this.provider.complete(messages, getToolDefinitions());

      if (!reply.tool_calls?.length) {
        const content = reply.content || "模型没有返回文本。";
        onEvent({ type: "answer", value: content });
        return content;
      }

      messages.push(reply);
      for (const call of reply.tool_calls) {
        const name = call.function?.name;
        onEvent({ type: "tool_start", name });
        const result = await executeTool(name, call.function?.arguments);
        onEvent({ type: "tool_end", name, result });
        messages.push({
          role: "tool",
          tool_call_id: call.id,
          content: JSON.stringify(result),
        });
      }
    }

    throw new Error(`Agent 超过最大执行步数 (${this.maxSteps})`);
  }
}
