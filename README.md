# Changqing Agent

一个不依赖 LangChain、LangGraph 或任何前端框架的最小 Agent 工作台。它只有 Node.js 运行时依赖，适合在此基础上继续实现自己的上下文、记忆、规划和工具系统。

## 快速启动

要求 Node.js 20 或更高版本。

```powershell
npm start
```

浏览器打开 <http://127.0.0.1:3000>。未配置模型时会进入演示模式，网页、会话和完整请求链路仍可使用。

## 接入模型

复制环境变量模板，再填写兼容 OpenAI Chat Completions 协议的服务：

```powershell
Copy-Item .env.example .env
```

至少填写：

```dotenv
OPENAI_API_KEY=你的密钥
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=你要使用的模型名称
```

修改配置后重启 `npm start`。

## 项目结构

```text
public/                 网页界面（原生 HTML/CSS/JavaScript）
src/server.js           HTTP、静态文件、REST 与 SSE 流式接口
src/store.js            JSON 会话存储
src/agent/agent.js      自写 Agent 执行循环
src/agent/provider.js   模型服务适配层
src/agent/tools.js      工具注册与执行协议
data/                   本地会话数据（已忽略提交）
```

## Agent 循环

`Agent.run()` 每一步把消息和工具定义发给模型。模型若返回 `tool_calls`，框架执行工具、追加工具结果，再进入下一步；模型返回普通文本时结束。默认最多 8 步，避免失控循环。

添加工具只需在 `src/agent/tools.js` 中调用 `registerTool()`，提供名称、描述、JSON Schema 参数和 `execute` 函数。后续可以继续扩展：

- token 级上游流式输出
- SQLite/PostgreSQL 持久化
- 文件、终端、搜索等工具及权限控制
- 上下文压缩和长期记忆
- 多 Agent 调度、暂停与人工确认

## 当前 API

- `GET /api/status`：运行模式和模型
- `GET/POST /api/conversations`：列出/创建会话
- `GET/DELETE /api/conversations/:id`：读取/删除会话
- `POST /api/chat`：运行 Agent，以 SSE 返回状态、工具和最终答案事件
