from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.dependencies import get_db

router = APIRouter()

@router.get("/command/suggest")
def get_command_suggestions(prefix: str, context: str = None, db: Session = Depends(get_db)):
    """获取CLI命令补全建议"""
    return {"suggestions": []}

@router.post("/command/record")
def record_cli_command(command: str, cwd: str, exit_code: int, duration: float):
    """记录CLI命令执行历史"""
    return {"status": "ok"}
