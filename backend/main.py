from fastapi import FastAPI
from dotenv import load_dotenv
from backend.dependencies import init_database_schema
from backend.routers import cli, feishu, memory

load_dotenv()

app = FastAPI(
    title="企业级记忆引擎API",
    description="飞书记忆引擎项目后端API服务",
    version="1.0.0"
)

# 注册路由
app.include_router(cli.cli_router, prefix="/api/v1", tags=["CLI端对接"])
app.include_router(memory.router, prefix="/api/v1/memory", tags=["记忆管理"])
app.include_router(feishu.router, prefix="/api/v1", tags=["飞书协同记忆"])


@app.on_event("startup")
def startup_event():
    init_database_schema()


@app.get("/health")
def health_check():
    return {"status": "ok", "message": "记忆引擎服务运行正常"}
