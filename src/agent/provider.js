function demoReply(messages) {
  const last = [...messages].reverse().find((message) => message.role === "user");
  const input = last?.content?.trim() || "你好";
  return {
    role: "assistant",
    content: `演示模式已收到：${input}\n\n当前网页、会话存储和 Agent 循环都已正常工作。配置 DASHSCOPE_API_KEY 或 OPENAI_API_KEY 后，我会切换到真实模型。`,
  };
}

export class OpenAICompatibleProvider {
  constructor({ apiKey, baseUrl, model }) {
    this.apiKey = apiKey;
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.model = model;
  }

  get isDemo() {
    return !this.apiKey;
  }

  async complete(messages, tools) {
    if (this.isDemo) return demoReply(messages);

    const response = await fetch(`${this.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${this.apiKey}`,
      },
      body: JSON.stringify({
        model: this.model,
        messages,
        tools,
        tool_choice: "auto",
        temperature: 0.4,
      }),
    });

    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`模型请求失败 (${response.status})：${detail.slice(0, 500)}`);
    }

    const data = await response.json();
    const message = data.choices?.[0]?.message;
    if (!message) throw new Error("模型响应中没有 message");
    return message;
  }
}
