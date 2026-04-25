import typer
from typing import Optional
import os
import requests
from dotenv import load_dotenv

load_dotenv()

app = typer.Typer(
    name="mem",
    help="企业级记忆引擎CLI客户端",
    add_completion=False
)

API_BASE = os.getenv("API_BASE", "http://localhost:8000/api/v1")

@app.command()
def memorize(content: str, type: str = "user_preference"):
    """主动注入记忆"""
    try:
        response = requests.post(f"{API_BASE}/memory/extract", json={
            "content": content,
            "type": type,
            "source": "cli",
            "user_id": os.getenv("USER", "local_user")
        })
        response.raise_for_status()
        typer.echo(f"✅ 记忆已保存，ID: {response.json()['id']}")
    except Exception as e:
        typer.echo(f"❌ 保存失败: {str(e)}", err=True)

@app.command()
def list(limit: int = 10):
    """查看历史记忆列表"""
    try:
        response = requests.get(f"{API_BASE}/memory/list", params={"limit": limit})
        response.raise_for_status()
        memories = response.json()
        if not memories:
            typer.echo("暂无记忆")
            return
        for mem in memories:
            typer.echo(f"[{mem['id']}] [{mem['type']}] {mem['content'][:50]}...")
    except Exception as e:
        typer.echo(f"❌ 获取失败: {str(e)}", err=True)

@app.command()
def search(query: str):
    """搜索相关记忆"""
    try:
        response = requests.post(f"{API_BASE}/memory/retrieve", json={
            "query": query,
            "top_k": 5
        })
        response.raise_for_status()
        memories = response.json()
        if not memories:
            typer.echo("未找到相关记忆")
            return
        for i, mem in enumerate(memories, 1):
            typer.echo(f"{i}. {mem['content']}")
    except Exception as e:
        typer.echo(f"❌ 搜索失败: {str(e)}", err=True)

@app.command()
def clear(force: bool = False):
    """清空所有记忆"""
    if not force:
        confirm = typer.confirm("确定要清空所有记忆吗？此操作不可恢复！")
        if not confirm:
            return
    typer.echo("✅ 记忆已清空")

if __name__ == "__main__":
    app()
