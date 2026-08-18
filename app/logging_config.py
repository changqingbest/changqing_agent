from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar, Token
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_conversation_id: ContextVar[str] = ContextVar("conversation_id", default="-")
_SECRET_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)\b(sk-[a-z0-9_-]{6,})\b"),
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;]+"),
)


def redact_text(value: str) -> str:
    """清除日志文本中常见的密钥形态，作为调用方不记录敏感值之外的第二道保护。"""
    redacted = value
    redacted = _SECRET_PATTERNS[0].sub(r"\1***", redacted)
    redacted = _SECRET_PATTERNS[1].sub("sk-***", redacted)
    redacted = _SECRET_PATTERNS[2].sub(r"\1***", redacted)
    return redacted


def _safe_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(str(value))


class ContextFilter(logging.Filter):
    """把当前异步请求的关联标识补到每条日志，不依赖全局可变变量。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        record.conversation_id = _conversation_id.get()
        return True


class SafeConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


class JsonFormatter(logging.Formatter):
    """输出一行一个 JSON 对象，便于检索、采集和故障时间线分析。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", "log"),
            "message": redact_text(record.getMessage()),
            "request_id": getattr(record, "request_id", "-"),
            "conversation_id": getattr(record, "conversation_id", "-"),
        }
        details = getattr(record, "details", None)
        if details:
            payload["details"] = _safe_value(details)
        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def bind_request_id(value: str) -> Token[str]:
    return _request_id.set(value)


def bind_conversation_id(value: str) -> Token[str]:
    return _conversation_id.set(value)


def reset_request_id(token: Token[str]) -> None:
    _request_id.reset(token)


def reset_conversation_id(token: Token[str]) -> None:
    _conversation_id.reset(token)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    message: str,
    *,
    exc_info: bool = False,
    **details: Any,
) -> None:
    """统一写入事件名与结构化详情；调用方只应传入非敏感元数据。"""
    logger.log(
        level,
        message,
        extra={"event": event, "details": details},
        exc_info=exc_info,
    )


def configure_logging(
    *,
    log_dir: Path,
    level: str = "INFO",
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> Path:
    """配置控制台和 UTF-8 JSONL 滚动文件；重复调用不会叠加处理器。"""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "changqing-agent.jsonl"
    root = logging.getLogger()

    for handler in list(root.handlers):
        if getattr(handler, "_changqing_handler", False):
            root.removeHandler(handler)
            handler.close()

    context_filter = ContextFilter()
    console = logging.StreamHandler(sys.stdout)
    console._changqing_handler = True  # type: ignore[attr-defined]
    console.addFilter(context_filter)
    console.setFormatter(
        SafeConsoleFormatter(
            "%(asctime)s %(levelname)s %(name)s "
            "[request=%(request_id)s conversation=%(conversation_id)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler._changqing_handler = True  # type: ignore[attr-defined]
    file_handler.addFilter(context_filter)
    file_handler.setFormatter(JsonFormatter())

    root.setLevel(numeric_level)
    root.addHandler(console)
    root.addHandler(file_handler)
    # httpx/httpcore 的 INFO 会包含带查询参数的完整 URL，可能间接暴露搜索词或地点。
    # 应用自己的 external_http.* 事件已经记录了主机、路径、状态和耗时，因此关闭重复明细。
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.captureWarnings(True)
    return log_file
