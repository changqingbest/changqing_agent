"""Changqing Agent 的 Python 核心包。"""

# 当前包初始化不创建服务对象，避免仅 import app 就触发模型、文件或端口副作用。
# 真正的命令入口在 app/__main__.py，Web 组装入口在 app/server.py。
