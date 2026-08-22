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

运行单元测试：

```powershell
python -m pytest tests/
```

## 核心结构

```text
app/
├── agent.py                         Agent Loop：模型、工具、结果的循环编排
├── config.py                        环境变量与端口配置
├── logging_config.py                结构化日志、滚动文件、上下文与敏感信息脱敏
├── prompt_manager.py                运行时解释器模板选择与 ReAct 系统提示词管理
├── prompts.py                       内置提示词分类与模板目录
├── react_protocol.py                Thought/Action/Observation 协议解析与动作映射
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

`AgentLoop.run()` 当前使用可观察的 ReAct 循环：

1. 根据最后一个用户问题自动选择通用、联网研究、编程诊断、数据计算、写作整理或部署运维解释器。
2. 把解释器要求、当前时间、工具目录和 ReAct 协议注入系统上下文。
3. 模型输出简短 `Thought` 和一个 `Action`，例如 `Search[关键词]` 或 `Calculate[{...}]`。
4. 框架执行动作，把真实结果作为 `Observation` 加回上下文并进入下一步。
5. 信息充分时模型输出 `Action: Finish[最终答案]`；最多执行 8 步，避免无限循环。

示例：

```text
Thought: 需要搜索官方发布信息。
Action: Search[华为最新手机型号及主要卖点]

Observation (Search): {"results": [...]}

Thought: 已获得足够的官方信息。
Action: Finish[完整答案]
```

网页通过 SSE 把解释器、步骤、思考摘要、行动和观察收集在对应的模型回答卡片中；右上角“过程记录”按钮可展开或隐藏，默认收起。这里的 `Thought` 被限定为简短行动理由，不要求或展示模型的详细私有推理。旧 Provider 如果仍返回 OpenAI 原生 `tool_calls`，循环会走兼容路径并产生相同的观察事件。

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

LOG_LEVEL=INFO
LOG_DIR=D:\\daima\\changqing_agent\\logs
LOG_MAX_BYTES=5242880
LOG_BACKUP_COUNT=5
```

## 日志与排障

服务同时输出适合本地观察的控制台日志，以及一行一个 JSON 对象的结构化日志：

```text
logs/changqing-agent.jsonl
logs/changqing-agent.jsonl.1
...
```

默认单个文件达到 5 MiB 后滚动，保留 5 份历史文件。可通过 `LOG_LEVEL`、`LOG_DIR`、`LOG_MAX_BYTES` 和 `LOG_BACKUP_COUNT` 调整；日志目录默认不提交到 Git。

日志覆盖服务启停、HTTP 请求、模型调用与 Token 用量、Agent 步骤、工具/PTC 执行、外部网络请求、会话存储和运行时模型切换。HTTP 响应会包含 `X-Request-ID`，同一请求的日志可用 `request_id` 串联；聊天任务还会记录 `conversation_id`。

安全边界：默认只记录正文长度、参数字段名、结果类型和耗时，不记录聊天正文、工具参数值、系统提示词、Authorization 或 API Key。日志格式化层还会对 `Bearer ...`、`sk-...` 和常见 `api_key=...` 文本进行二次脱敏。

## 内置工具

- `get_current_time`：查询指定 IANA 时区的当前日期、时间、中文星期、ISO 星期序号和 UTC 偏移，避免模型自行推算星期。
- `calculate`：加、减、乘、除基础计算。
- `web_search`：返回可供 Agent 引用的标题、链接和摘要；配置 `TAVILY_API_KEY` 时使用 Tavily，未配置时按查询类型使用免密钥 RSS 搜索。
- `get_weather`：通过 Open-Meteo 查询地点、当前天气及未来 1～7 天预报，无需 API Key。

网络工具统一设置连接/读取超时。它们仍通过同一个 `ToolRegistry` 暴露给普通 function calling 和 PTC；Agent Loop 会在线程中执行同步工具，避免网络请求阻塞 FastAPI 事件循环。

### 千问原生联网搜索

当模型使用百炼 OpenAI 兼容端点时，默认开启千问原生联网搜索。模型设置面板可以关闭此能力、选择 `turbo`/`max` 搜索策略，或开启强制搜索。实现按照[阿里云百炼联网搜索文档](https://help.aliyun.com/zh/model-studio/web-search)，在 Chat Completions 请求中发送：

```json
{
  "enable_search": true,
  "search_options": {
    "search_strategy": "turbo",
    "forced_search": false
  }
}
```

千问原生搜索用于模型侧实时信息增强；OpenAI 兼容协议不会返回独立来源列表。需要明确标题和链接时，Agent 仍可调用 `web_search` 函数工具。切换到非百炼端点后不会发送这些千问专有字段。

## 提示词模板

网页输入框左下角的“模板”按钮提供 8 个分类、24 个内置模板，覆盖通用问答、联网调研、编程开发、写作总结、数据分析、效率办公、创意多媒体和部署运维。选择模板只会填入输入框，用户可替换 `【占位内容】` 后再发送。

模板数据由 `GET /api/prompt-templates` 提供；新增模板时编辑 `app/prompts.py` 即可，无需修改前端渲染逻辑。

运行时解释器提示词由 `app/prompt_manager.py` 单独管理，不同问题会自动选择不同模板并注入 Agent 上下文。可通过 `GET /api/interpreter-templates` 查看当前解释器目录；它与上面的输入框模板互不影响。

## API

- `GET /api/status`：运行模式、模型、PTC 状态和端口
- `GET /api/prompt-templates`：提示词分类与模板目录
- `GET /api/interpreter-templates`：ReAct 运行时解释器模板目录
- `GET/POST /api/model-config`：读取或切换当前进程的模型配置；API Key 不回显、不落盘
- `GET/POST /api/conversations`：列出或创建会话
- `GET/DELETE /api/conversations/{id}`：读取或删除会话
- `POST /api/chat`：运行 Agent，以 SSE 返回状态、工具和最终答案事件
