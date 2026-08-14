from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


# ConversationStore 是最小 JSON 持久化层，负责会话的增删查和消息追加。
# 它适合单进程本地原型；多进程或多机器部署时应替换成 SQLite/PostgreSQL 等数据库。
class ConversationStore:
    # data_file：保存全部会话的 JSON 文件绝对或相对路径。
    # 副作用：只创建进程内异步锁，不会在构造时创建或读取文件。
    def __init__(self, data_file: Path) -> None:
        # 所有读写始终使用这个目标路径，调用方负责选择项目内的安全位置。
        self.data_file = data_file
        # 锁防止同一事件循环内多个请求同时“读取旧值再覆盖写入”造成消息丢失。
        # 注意：asyncio.Lock 不能协调多个独立 Python 进程。
        self._lock = asyncio.Lock()

    # 作用：同步读取并解析完整会话文件；只在持有 _lock 的公开方法中调用。
    # 返回：文件不存在时为空列表，否则返回 JSON 解码后的会话列表。
    # 异常：文件损坏、编码错误或权限错误会向上抛出，避免默默清空用户数据。
    def _read(self) -> list[dict[str, Any]]:
        # 首次启动没有 conversations.json 属于正常情况。
        if not self.data_file.exists():
            return []
        return json.loads(self.data_file.read_text(encoding="utf-8"))

    # 作用：把完整会话列表以 UTF-8 JSON 原子替换到目标文件。
    # items：当前所有会话；返回值：无；副作用：创建目录并写磁盘。
    # 实现：先写同目录临时文件，再 replace，降低进程中途退出导致半截 JSON 的风险。
    def _write(self, items: list[dict[str, Any]]) -> None:
        # parents=True 允许 data 目录尚不存在；exist_ok=True 允许重复启动。
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        # 临时文件与目标文件位于同一目录，通常可由操作系统完成原子替换。
        temporary = self.data_file.with_suffix(".tmp")
        # ensure_ascii=False 让人工打开数据文件时能直接阅读中文。
        temporary.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.data_file)

    # 作用：返回左侧任务列表需要的轻量摘要，而不是把全部消息正文发给前端。
    # 返回：按 updatedAt 从新到旧排列的摘要列表。
    # 并发：读取阶段持锁，离开锁后只处理本地快照。
    async def list(self) -> list[dict[str, Any]]:
        async with self._lock:
            items = self._read()
        # messageCount 由当前 messages 长度即时计算，不在文件中重复保存派生字段。
        summaries = [
            {
                "id": item["id"],
                "title": item["title"],
                "createdAt": item["createdAt"],
                "updatedAt": item["updatedAt"],
                "messageCount": len(item["messages"]),
            }
            for item in items
        ]
        # ISO UTC 时间字符串可直接按字典序排序，reverse=True 让最新会话排在最前。
        return sorted(summaries, key=lambda item: item["updatedAt"], reverse=True)

    # 作用：按 UUID 查找一个完整会话。
    # conversation_id：URL 中的会话标识；返回匹配字典，不存在时返回 None。
    async def get(self, conversation_id: str) -> dict[str, Any] | None:
        async with self._lock:
            return next((item for item in self._read() if item["id"] == conversation_id), None)

    # 作用：创建空会话、写入磁盘并返回新会话。
    # 字段：id 是 UUID；createdAt/updatedAt 使用带时区 UTC ISO 时间；messages 初始为空。
    async def create(self) -> dict[str, Any]:
        async with self._lock:
            # 必须在锁内完成“读—追加—写”，保证单进程并发请求不会相互覆盖。
            items = self._read()
            now = datetime.now(UTC).isoformat()
            conversation = {
                "id": str(uuid4()),
                "title": "新任务",
                "createdAt": now,
                "updatedAt": now,
                "messages": [],
            }
            # 先修改内存快照，再一次性持久化完整列表。
            items.append(conversation)
            self._write(items)
            return conversation

    # 作用：向指定会话追加一条消息，并更新标题和最后修改时间。
    # role：通常为 user 或 assistant；content：消息正文；返回更新后的完整会话。
    # 异常：会话不存在时抛 KeyError，由 Web 层转换成 HTTP 404。
    async def add_message(self, conversation_id: str, role: str, content: str) -> dict[str, Any]:
        async with self._lock:
            items = self._read()
            # 基础 JSON 存储采用线性搜索；会话量大时数据库索引会更合适。
            conversation = next((item for item in items if item["id"] == conversation_id), None)
            if conversation is None:
                raise KeyError("会话不存在")
            # 每条消息拥有独立 UUID 和创建时间，便于未来做编辑、引用或审计。
            conversation["messages"].append(
                {
                    "id": str(uuid4()),
                    "role": role,
                    "content": content,
                    "createdAt": datetime.now(UTC).isoformat(),
                }
            )
            # 只有第一条用户消息会自动生成标题；后续追问不会改变左侧任务名称。
            if role == "user" and sum(m["role"] == "user" for m in conversation["messages"]) == 1:
                # 合并多余空白并限制 28 字符，避免换行或超长内容破坏侧栏布局。
                conversation["title"] = " ".join(content.split())[:28] or "新任务"
            # 任意角色新增消息都会把会话移动到任务列表顶部。
            conversation["updatedAt"] = datetime.now(UTC).isoformat()
            self._write(items)
            return conversation

    # 作用：删除指定会话及其全部消息。
    # 返回：确实删除为 True；找不到目标为 False，调用方据此返回 404。
    # 风险：这是不可恢复的物理删除，生产版可改成软删除或回收站机制。
    async def delete(self, conversation_id: str) -> bool:
        async with self._lock:
            items = self._read()
            # 创建新列表而不是遍历时原地删除，逻辑更清晰且避免跳项。
            remaining = [item for item in items if item["id"] != conversation_id]
            # 长度未变化说明目标不存在，此时不要无意义重写数据文件。
            if len(remaining) == len(items):
                return False
            self._write(remaining)
            return True
