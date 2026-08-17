# Changqing Agent

一个使用 Python 从零实现的最小 Agent 工作台，不依赖 LangChain、LangGraph 或其他 Agent 框架。网页保留原生 HTML/CSS/JavaScript，Python 后端负责 Agent Loop、PTC、模型调用、会话存储和 SSE 事件流。

## 启动

要求 Python 3.11 或更高版本：

```powershell
cd D:\daima\changqing_agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app
```

默认访问地址：<http://127.0.0.1:8008>。

本机已有 `DASHSCOPE_API_KEY` 时会自动接入阿里云百炼 `qwen-plus`，不会把密钥复制到项目文件。没有密钥时进入演示模式。

模型与 PTC 连通性检查：

```powershell
python -m scripts.verify_model
```

## 核心结构

```text
app/
├── agent.py                         Agent Loop：模型、工具、结果的循环编排
├── config.py                        环境变量与端口配置
├── server.py                        FastAPI、REST、SSE 和静态网页
├── store.py                         JSON 会话存储
├── providers/openai_compatible.py   千问/OpenAI 兼容模型适配层
├── tools/registry.py                工具注册、Schema 和调度
├── tools/network.py                 联网搜索和天气查询
└── ptc/executor.py                  PTC 受限 Python 解释执行层
public/                              原生网页
scripts/verify_model.py              真实模型与 PTC 验证脚本
```

## Agent Loop

`AgentLoop.run()` 的最小流程：

1. 系统提示词和会话消息交给模型。
2. 模型返回普通文本时，结束本轮。
3. 模型返回工具调用时，交给工具层或 PTC 层执行。
4. 执行结果作为 `tool` 消息返回模型，再进入下一步。
5. 最多执行 8 步，避免无限循环。

核心类没有依赖 FastAPI，可以独立用于 CLI、定时任务或其他服务。

## PTC 层

PTC（Programmatic Tool Calling）允许模型生成一小段程序，在一次工具调用中编排多个已注册工具：

```python
time_result = get_current_time(time_zone="Asia/Shanghai")
math_result = calculate(operation="multiply", left=6, right=7)
emit({"time": time_result, "math": math_result})
```

`PTCExecutor` 不会调用 Python 的 `exec()`。它解释 AST 白名单，只允许：

- 赋值、`if`、`for` 和基础表达式
- 列表、元组、字典及下标访问
- 少量安全内置函数
- 已注册工具和 `emit()`

它拒绝 `import`、属性访问、文件操作、网络访问、函数/类定义及任意系统调用。这只是最小安全边界；未来若要执行通用模型代码，应改用独立 Docker/虚拟机沙箱。

## 配置

程序优先使用显式的通用 OpenAI 配置，其次使用千问配置：

```dotenv
DASHSCOPE_API_KEY=
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus

OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini

HOST=127.0.0.1
PORT=8008
SYSTEM_PROMPT=你是常青 Agent。回答准确、简洁；需要时主动调用工具。
TAVILY_API_KEY=
```

## 内置工具

- `get_current_time`：查询指定 IANA 时区的当前时间。
- `calculate`：加、减、乘、除基础计算。
- `web_search`：互联网搜索；配置 `TAVILY_API_KEY` 时使用 Tavily，未配置时使用免密钥 Bing RSS。
- `get_weather`：通过 Open-Meteo 查询地点、当前天气及未来 1～7 天预报，无需 API Key。

网络工具统一设置连接/读取超时。它们仍通过同一个 `ToolRegistry` 暴露给普通 function calling 和 PTC；Agent Loop 会在线程中执行同步工具，避免网络请求阻塞 FastAPI 事件循环。

## API

- `GET /api/status`：运行模式、模型、PTC 状态和端口
- `GET/POST /api/conversations`：列出或创建会话
- `GET/DELETE /api/conversations/{id}`：读取或删除会话
- `POST /api/chat`：运行 Agent，以 SSE 返回状态、工具和最终答案事件
