const registry = new Map();

export function registerTool(tool) {
  if (!tool?.name || typeof tool.execute !== "function") {
    throw new Error("工具必须包含 name 和 execute");
  }
  registry.set(tool.name, tool);
}

export function getToolDefinitions() {
  return [...registry.values()].map(({ name, description, parameters }) => ({
    type: "function",
    function: { name, description, parameters },
  }));
}

export async function executeTool(name, rawArguments) {
  const tool = registry.get(name);
  if (!tool) return { error: `未注册的工具：${name}` };

  try {
    const args = typeof rawArguments === "string"
      ? JSON.parse(rawArguments || "{}")
      : rawArguments ?? {};
    return await tool.execute(args);
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
}

registerTool({
  name: "get_current_time",
  description: "获取指定时区的当前日期和时间。",
  parameters: {
    type: "object",
    properties: {
      timeZone: {
        type: "string",
        description: "IANA 时区，例如 Asia/Shanghai",
      },
    },
    required: [],
    additionalProperties: false,
  },
  execute: ({ timeZone = "Asia/Shanghai" }) => ({
    timeZone,
    value: new Intl.DateTimeFormat("zh-CN", {
      dateStyle: "full",
      timeStyle: "long",
      timeZone,
    }).format(new Date()),
  }),
});
