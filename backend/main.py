from fastapi import FastAPI
from dotenv import load_dotenv
from backend.routers import cli

load_dotenv()

app = FastAPI(
    title="企业级记忆引擎API",
    description="飞书记忆引擎项目后端API服务",
    version="1.0.0"
)

# 注册路由
app.include_router(cli.cli_router, prefix="/api/v1", tags=["CLI端对接"])

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "记忆引擎服务运行正常"}
