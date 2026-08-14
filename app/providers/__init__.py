"""模型 Provider 适配层。"""

# Provider 子包用于隔离不同模型协议；当前实现位于 openai_compatible.py。
# 保持包初始化轻量，导入本包本身不会创建 HTTP 客户端或发起网络请求。
