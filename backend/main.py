from contextlib import asynccontextmanager

from fastapi import FastAPI
from dotenv import load_dotenv
from backend.dependencies import init_database_schema
from backend.routers import cli, feishu, memory, health

load_dotenv(override=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    init_database_schema()
    yield
    # 关闭时执行（如果需要）


app = FastAPI(
    title="企业级记忆引擎API",
    description="飞书记忆引擎项目后端API服务",
    version="1.0.0",
    lifespan=lifespan
)

# 注册路由
app.include_router(cli.cli_router, prefix="/api/v1", tags=["CLI端对接"])
app.include_router(memory.router, prefix="/api/v1/memory", tags=["记忆管理"])
app.include_router(feishu.router, prefix="/api/v1", tags=["飞书协同记忆"])
app.include_router(health.router, tags=["健康检查"])


@app.get("/health")
def health_check():
    return {"status": "ok", "message": "记忆引擎服务运行正常"}
