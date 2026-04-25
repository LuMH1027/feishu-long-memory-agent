from fastapi import FastAPI
from dotenv import load_dotenv
from backend.routers import memory, cli, feishu

load_dotenv()

app = FastAPI(
    title="企业级记忆引擎API",
    description="飞书记忆引擎项目后端API服务",
    version="1.0.0"
)

# 注册路由
app.include_router(memory.router, prefix="/api/v1/memory", tags=["记忆管理"])
app.include_router(cli.router, prefix="/api/v1/cli", tags=["CLI端对接"])
app.include_router(feishu.router, prefix="/api/v1/feishu", tags=["飞书端对接"])

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "记忆引擎服务运行正常"}
