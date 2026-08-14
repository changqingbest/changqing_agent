import uvicorn

from app.config import settings


# 该文件让项目支持 `python -m app` 启动。
# 直接导入 app 包时不会启动服务器，只有作为主模块运行才进入下面分支。
if __name__ == "__main__":
    # 使用字符串形式 app.server:app 可避免这里提前手动导入 Web 应用。
    # host/port 来自统一 Settings；reload=False 适合作为稳定的基础启动方式。
    uvicorn.run("app.server:app", host=settings.host, port=settings.port, reload=False)
