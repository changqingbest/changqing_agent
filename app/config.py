from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


# 本文件是整个应用的“配置入口”：它只负责把环境变量整理成结构化对象，
# 不负责调用模型、启动服务或执行业务逻辑。把配置集中在这里的好处是，
# 其他模块只依赖 Settings，不需要到处散落 os.getenv()。

# 项目根目录。__file__ 指向 app/config.py，连续两次 parent 后得到仓库根目录。
# 后续寻找 .env、data、public 等目录时都以它为基准，避免受启动工作目录影响。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 阿里云百炼北京地域的 OpenAI 兼容接口根地址。这里只保存根地址，
# Provider 会在其后拼接 /chat/completions。
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


# 作用：读取项目根目录下可选的 .env 文件，并补充到当前进程环境变量中。
# 参数：无。返回值：无；结果通过 os.environ 产生进程内副作用。
# 边界：这只是最小 KEY=VALUE 解析器，不支持多行值、变量插值等完整 dotenv 语法。
# 安全：使用 setdefault，不会用项目 .env 覆盖用户已经在系统中设置的密钥。
def _load_dotenv() -> None:
    """读取最基础的 KEY=VALUE 配置，不覆盖系统环境变量。"""
    # .env 只用于本地开发，已被 .gitignore 排除，不应提交真实 API Key。
    env_file = PROJECT_ROOT / ".env"
    # 文件不存在属于正常情况：本机可能直接配置了系统环境变量。
    if not env_file.exists():
        return

    # 按行解析可以保持实现零额外依赖；空行、注释行和不含等号的行直接跳过。
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        # 只按第一个等号切分，确保值本身即使含有“=”也不会被截断。
        key, value = line.split("=", 1)
        # 去掉键两侧空白及值最外层的单/双引号；已有系统变量优先级更高。
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


# frozen=True：配置创建后不允许被意外修改；slots=True：固定字段并减少实例开销。
# 每个字段都是“启动时快照”，修改系统环境变量后需要重启进程才会重新读取。
@dataclass(frozen=True, slots=True)
class Settings:
    # 调用模型服务所需的密钥。只保存在内存中，不应写入日志或返回前端。
    api_key: str
    # 模型服务根地址，例如百炼 compatible-mode/v1；结尾统一不带斜杠。
    base_url: str
    # 发给兼容接口的模型标识，例如 qwen-plus。
    model: str
    # 展示用的供应商名称，不参与鉴权或路由判断。
    provider_name: str
    # Web 服务监听地址。127.0.0.1 表示默认只允许本机访问。
    host: str
    # Web 服务监听端口，默认 8008；必须能转换为整数。
    port: int
    # 每轮对话放在最前面的系统指令，用来规定 Agent 的身份与行为原则。
    system_prompt: str

    # 作用：用统一属性判断是否缺少模型密钥。
    # 返回：True 表示 Provider 应走本地演示回复；False 表示可调用真实模型。
    @property
    def is_demo(self) -> bool:
        return not self.api_key


# 作用：按照明确优先级读取环境变量并构造 Settings。
# 优先级：通用 OPENAI_* > 千问 DASHSCOPE_* > 无密钥演示模式。
# 返回：不可变的 Settings 实例。
# 异常：PORT 不是整数时 int() 会抛出 ValueError，让错误尽早暴露在启动阶段。
def load_settings() -> Settings:
    # 先加载项目级配置；系统环境变量因为 setdefault 机制仍保持最高来源优先级。
    _load_dotenv()

    # 显式配置通用 OpenAI 密钥时，认为用户有意覆盖千问默认配置。
    if os.getenv("OPENAI_API_KEY"):
        api_key = os.environ["OPENAI_API_KEY"]
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        provider_name = "OpenAI Compatible"
    # 没有通用配置但存在百炼密钥时，自动接入本机的千问环境。
    elif os.getenv("DASHSCOPE_API_KEY"):
        api_key = os.environ["DASHSCOPE_API_KEY"]
        base_url = os.getenv("DASHSCOPE_BASE_URL", DASHSCOPE_BASE_URL)
        model = os.getenv("QWEN_MODEL", "qwen-plus")
        provider_name = "Qwen / DashScope"
    # 两种密钥都没有时保留可启动状态，Provider 会返回演示文本而不是请求网络。
    else:
        api_key = ""
        base_url = DASHSCOPE_BASE_URL
        model = os.getenv("QWEN_MODEL", "qwen-plus")
        provider_name = "Demo"

    # 在边界处完成类型转换与地址规范化，后续模块无需重复处理。
    return Settings(
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        model=model,
        provider_name=provider_name,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8008")),
        system_prompt=os.getenv(
            "SYSTEM_PROMPT",
            "你是常青 Agent。回答准确、简洁；需要时主动调用工具。复杂的多工具任务优先使用 PTC。",
        ),
    )


# 模块导入时只加载一次，供 Server、验证脚本等模块共享同一份启动配置。
# 若测试需要不同配置，应直接调用 load_settings() 或在导入前设置环境变量。
settings = load_settings()
