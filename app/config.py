from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _load_dotenv() -> None:
    """读取最基础的 KEY=VALUE 配置，不覆盖系统环境变量。"""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


@dataclass(frozen=True, slots=True)
class Settings:
    api_key: str
    base_url: str
    model: str
    provider_name: str
    host: str
    port: int
    system_prompt: str

    @property
    def is_demo(self) -> bool:
        return not self.api_key


def load_settings() -> Settings:
    _load_dotenv()

    if os.getenv("OPENAI_API_KEY"):
        api_key = os.environ["OPENAI_API_KEY"]
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        provider_name = "OpenAI Compatible"
    elif os.getenv("DASHSCOPE_API_KEY"):
        api_key = os.environ["DASHSCOPE_API_KEY"]
        base_url = os.getenv("DASHSCOPE_BASE_URL", DASHSCOPE_BASE_URL)
        model = os.getenv("QWEN_MODEL", "qwen-plus")
        provider_name = "Qwen / DashScope"
    else:
        api_key = ""
        base_url = DASHSCOPE_BASE_URL
        model = os.getenv("QWEN_MODEL", "qwen-plus")
        provider_name = "Demo"

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


settings = load_settings()
