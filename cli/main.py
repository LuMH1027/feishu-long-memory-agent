import typer
from typing import Any, List, Optional
import os
import requests
from dotenv import load_dotenv
from pathlib import Path
import configparser
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime

import pyperclip

# --- 配置管理 ---
CONFIG_DIR = Path.home() / ".mem_agent"
CONFIG_FILE = CONFIG_DIR / "config.ini"

def get_api_base() -> str:
    """获取API基础地址，优先从全局配置读取，其次是.env文件"""
    # 1. 尝试从全局配置读取
    if CONFIG_FILE.exists():
        config = configparser.ConfigParser()
        config.read(CONFIG_FILE)
        if "default" in config and "api_base" in config["default"]:
            return config["default"]["api_base"]
    
    # 2. 兼容本地开发，从.env文件读取
    load_dotenv(override=True)
    return os.getenv("API_BASE", "http://localhost:8000/api/v1")

API_BASE = get_api_base()

# --- Typer 应用定义 ---
app = typer.Typer(
    name="mem",
    help="企业级记忆引擎CLI客户端",
    add_completion=False
)
workflow_app = typer.Typer(help="工作流模板管理")
app.add_typer(workflow_app, name="workflow")


def _request(method: str, path: str, **kwargs: Any) -> requests.Response:
    """Send an API request using the latest configured base URL."""
    return requests.request(method, f"{get_api_base()}{path}", **kwargs)


def _current_directory() -> str:
    """Return the current working directory as CLI context."""
    return str(Path.cwd())


def _record_command_usage(command: str, exit_code: Optional[int] = None) -> None:
    """Best-effort feedback loop for executed commands."""
    payload: dict[str, Any] = {
        "command": command,
        "count": 1,
        "shell": os.getenv("SHELL", "powershell"),
        "directory": _current_directory(),
    }
    if exit_code is not None:
        payload["exit_code"] = exit_code
    try:
        response = _request("POST", "/cli/command/record", json=payload)
        response.raise_for_status()
    except requests.RequestException:
        pass


def _normalize_result(result: dict[str, Any]) -> dict[str, Any]:
    """Unify memory and CLI-command result shapes for CLI rendering."""
    metadata = result.get("metadata") or {}
    if "count" in result:
        metadata = {**metadata, "count": result.get("count")}
    if "last_used" in result:
        metadata = {**metadata, "last_used_at": result.get("last_used")}
    content = result.get("content") or result.get("command") or ""
    return {
        "content": content,
        "type": result.get("type") or metadata.get("type"),
        "description": result.get("description") or result.get("summary") or "无描述",
        "metadata": metadata,
    }


def _search_memories(
    query: str,
    limit: int,
    memory_type: Optional[str] = None,
    directory: Optional[str] = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"query": query, "limit": limit}
    if memory_type:
        params["type"] = memory_type
    if directory:
        params["directory"] = directory

    results = []
    try:
        response = _request("GET", "/memory/search", params=params)
        response.raise_for_status()
        results = response.json()
    except requests.RequestException:
        results = []

    if not results:
        response = _request("POST", "/memory/retrieve", json={"query": query, "top_k": limit})
        response.raise_for_status()
        results = response.json()

    normalized = [_normalize_result(item) for item in results]
    if memory_type:
        normalized = [item for item in normalized if item.get("type") == memory_type]
    if normalized:
        return normalized[:limit]

    try:
        response = _request(
            "POST",
            "/cli/command/suggest",
            json={
                "partial_command": query,
                "shell": os.getenv("SHELL", "powershell"),
                "directory": directory or _current_directory(),
            },
        )
        response.raise_for_status()
        suggestions = response.json().get("suggestions", [])
    except requests.RequestException:
        suggestions = []

    command_results = [_normalize_result({**item, "type": "cli_command"}) for item in suggestions]
    if memory_type:
        command_results = [item for item in command_results if item.get("type") == memory_type]
    return command_results[:limit]

# --- 命令实现 ---

@app.command()
def configure():
    """配置CLI工具，如API服务器地址"""
    api_base = typer.prompt("请输入记忆引擎API服务器地址", default=API_BASE)
    
    # 创建配置目录
    CONFIG_DIR.mkdir(exist_ok=True)
    
    # 写入配置
    config = configparser.ConfigParser()
    config["default"] = {"api_base": api_base}
    with open(CONFIG_FILE, "w") as configfile:
        config.write(configfile)
        
    typer.echo(f"✅ 配置已保存到 {CONFIG_FILE}")

@app.command()
def memorize(content: str, type: str = "user_preference"):
    """主动注入记忆"""
    try:
        response = _request("POST", "/memory/extract", json={
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
        memories = []
        try:
            response = _request("GET", "/memory/list", params={"limit": limit})
            response.raise_for_status()
            memories.extend(response.json())
        except requests.RequestException:
            pass

        try:
            response = _request("GET", "/cli/command/list", params={"limit": limit})
            response.raise_for_status()
            memories.extend(_normalize_result(item) for item in response.json())
        except requests.RequestException:
            pass

        if not memories:
            typer.echo("暂无记忆")
            return
        for mem in memories:
            typer.echo(f"[{mem.get('id', '-')}] [{mem.get('type', 'unknown')}] {mem.get('content', '')[:50]}...")
    except Exception as e:
        typer.echo(f"❌ 获取失败: {str(e)}", err=True)

@app.command()
def search(
    query: str = typer.Argument(..., help="搜索关键词"),
    limit: int = typer.Option(5, help="返回结果数量"),
    execute: bool = typer.Option(False, help="直接执行第一个匹配的命令"),
    copy: bool = typer.Option(False, help="直接复制第一个匹配的命令到剪贴板"),
    type: Optional[str] = typer.Option(None, help="按记忆类型过滤"),
):
    """搜索相关记忆"""
    try:
        results = _search_memories(query, limit, type, _current_directory())
        if not results:
            typer.echo("❌ 没有找到相关记忆")
            return

        if execute:
            cmd = results[0]["content"]
            typer.echo(f"🚀 执行命令：{cmd}")
            completed = subprocess.run(cmd, shell=True)
            _record_command_usage(cmd, getattr(completed, "returncode", None))
            return

        if copy:
            cmd = results[0]["content"]
            pyperclip.copy(cmd)
            typer.echo(f"✅ 已复制到剪贴板：{cmd}")
            return

        typer.echo("找到以下相关命令：")
        for i, result in enumerate(results, 1):
            typer.echo(f"\n{i}. {result['content']}")
            typer.echo(f"   描述：{result.get('description', '无描述')}")
            typer.echo(f"   使用次数：{result.get('metadata', {}).get('count', 0)}")

        if not sys.stdin.isatty():
            return

        selected = typer.prompt(
            "\n请选择要执行/复制的命令序号（输入0退出）",
            type=int,
            default=0,
        )
        if selected <= 0:
            return
        if selected > len(results):
            typer.echo("❌ 无效的序号")
            return

        cmd = results[selected - 1]["content"]
        action = typer.prompt("请选择操作：1=执行 2=复制", type=int, default=1)
        if action == 1:
            completed = subprocess.run(cmd, shell=True)
            _record_command_usage(cmd, getattr(completed, "returncode", None))
        elif action == 2:
            pyperclip.copy(cmd)
            typer.echo("✅ 已复制到剪贴板")
        else:
            typer.echo("❌ 无效的操作")
    except Exception as e:
        typer.echo(f"❌ 搜索失败: {str(e)}", err=True)


@app.command()
def suggest(
    prefix: str = typer.Argument(..., help="Command prefix or keywords"),
    limit: int = typer.Option(5, help="Maximum number of suggestions"),
):
    """Output command suggestions for shell completion integrations."""
    try:
        response = _request(
            "POST",
            "/cli/command/suggest",
            json={
                "partial_command": prefix,
                "shell": os.getenv("SHELL", "powershell"),
                "directory": _current_directory(),
            },
        )
        response.raise_for_status()
        suggestions = response.json().get("suggestions", [])
        for item in suggestions[:limit]:
            command = item.get("command")
            if command:
                typer.echo(command)
    except Exception as e:
        typer.echo(f"推荐失败: {str(e)}", err=True)


# --- Completion 子命令 ---
completion_app = typer.Typer(help="管理shell补全")
app.add_typer(completion_app, name="completion")


@completion_app.command("install")
def completion_install(
    shell: Optional[str] = typer.Option(None, help="Shell类型：powershell/bash/zsh（自动检测）"),
    force: bool = typer.Option(False, help="强制覆盖已有脚本"),
):
    """安装shell补全脚本"""
    from cli.completion import install_completion, get_setup_instructions

    result = install_completion(shell_type=shell, force=force)

    if result["status"] == "ok":
        typer.echo(f"✅ {result['message']}")
        typer.echo(f"\n激活命令: {result['activate_command']}")
        typer.echo("\n要永久激活，请将激活命令添加到shell配置文件中。")
        typer.echo("\n详细说明:")
        typer.echo(get_setup_instructions(shell))
    elif result["status"] == "skipped":
        typer.echo(f"⚠️ {result['message']}")
        typer.echo(f"提示: {result.get('hint', '')}")
    else:
        typer.echo(f"❌ 安装失败: {result.get('message', '未知错误')}", err=True)


@completion_app.command("uninstall")
def completion_uninstall(
    shell: Optional[str] = typer.Option(None, help="Shell类型：powershell/bash/zsh（自动检测）"),
):
    """卸载shell补全脚本"""
    from cli.completion import uninstall_completion

    result = uninstall_completion(shell_type=shell)

    if result["status"] == "ok":
        typer.echo(f"✅ {result['message']}")
    else:
        typer.echo(f"⚠️ {result['message']}")


@completion_app.command("show")
def completion_show(
    shell: Optional[str] = typer.Option(None, help="Shell类型：powershell/bash/zsh（自动检测）"),
):
    """显示补全脚本内容"""
    from cli.completion import get_completion_script

    script = get_completion_script(shell)
    typer.echo(script)


@app.command()
def watch(
    shell: str = typer.Option("powershell", help="要监控的shell类型：powershell/bash/zsh"),
    auto_record_threshold: int = typer.Option(3, help="命令使用多少次后自动记录"),
):
    """扫描命令行历史，自动记录高频命令"""
    history_files = {
        "powershell": Path.home()
        / "AppData"
        / "Roaming"
        / "Microsoft"
        / "Windows"
        / "PowerShell"
        / "PSReadLine"
        / "ConsoleHost_history.txt",
        "bash": Path.home() / ".bash_history",
        "zsh": Path.home() / ".zsh_history",
    }
    if shell not in history_files:
        typer.echo(f"❌ 不支持的shell类型：{shell}", err=True)
        raise typer.Exit(code=1)

    history_file = history_files[shell]
    if not history_file.exists():
        typer.echo(f"❌ 未找到历史文件：{history_file}", err=True)
        raise typer.Exit(code=1)

    with open(history_file, "r", encoding="utf-8", errors="ignore") as f:
        commands = [
            line.strip()
            for line in f
            if line.strip() and not line.lstrip().startswith("#")
        ]

    command_counts = Counter(commands)
    recorded_count = 0
    for cmd, count in command_counts.items():
        if count < auto_record_threshold or len(cmd) <= 10:
            continue
        try:
            response = _request(
                "POST",
                "/cli/command/record",
                json={"command": cmd, "count": count, "shell": shell, "directory": _current_directory()},
            )
            response.raise_for_status()
            recorded_count += 1
        except requests.RequestException:
            continue

    typer.echo(f"✅ 已扫描历史命令，自动记录了{recorded_count}条高频命令")


@workflow_app.command("save")
def save_workflow(
    name: str = typer.Argument(..., help="工作流名称"),
    steps: List[str] = typer.Argument(..., help="工作流步骤命令，多词命令请用引号包裹"),
):
    """保存工作流模板"""
    workflow = {
        "name": name,
        "steps": steps,
        "created_at": datetime.now().isoformat(),
    }
    payload = {
        "content": json.dumps(workflow, ensure_ascii=False),
        "type": "cli_workflow",
        "description": f"工作流：{name}",
        "metadata": workflow,
    }

    try:
        try:
            response = _request("POST", "/memory/", json=payload)
            response.raise_for_status()
        except requests.RequestException:
            response = _request(
                "POST",
                "/memory/extract",
                json={
                    "content": payload["content"],
                    "type": payload["type"],
                    "source": "cli",
                    "user_id": os.getenv("USER", "local_user"),
                },
            )
            response.raise_for_status()
        typer.echo(f"✅ 工作流《{name}》已保存，包含{len(steps)}个步骤")
    except Exception as e:
        typer.echo(f"❌ 保存工作流失败: {str(e)}", err=True)


@workflow_app.command("list")
def list_workflows(limit: int = typer.Option(10, help="返回数量")):
    """列出已保存的工作流"""
    try:
        response = _request("GET", "/cli/command/list", params={"limit": limit, "type": "cli_workflow"})
        response.raise_for_status()
        workflows = response.json()
        if not workflows:
            typer.echo("暂无工作流")
            return
        for wf in workflows:
            content = wf.get("content", "")
            try:
                data = json.loads(content)
                name = data.get("name", "未知")
                steps = data.get("steps", [])
                typer.echo(f"📋 {name} ({len(steps)} 步)")
                for i, s in enumerate(steps, 1):
                    typer.echo(f"   {i}. {s}")
            except json.JSONDecodeError:
                typer.echo(f"📋 {content[:60]}")
    except Exception as e:
        typer.echo(f"❌ 获取工作流失败: {str(e)}", err=True)


@workflow_app.command("run")
def run_workflow(name: str = typer.Argument(..., help="工作流名称")):
    """执行已保存的工作流"""
    try:
        results = _search_memories(name, 1, "cli_workflow", _current_directory())
        if not results:
            typer.echo(f"❌ 未找到工作流《{name}》")
            return

        workflow = json.loads(results[0]["content"])
        steps = workflow.get("steps", [])
        typer.echo(f"🚀 开始执行工作流《{name}》，共{len(steps)}个步骤")

        for i, step in enumerate(steps, 1):
            typer.echo(f"\n步骤 {i}/{len(steps)}: {step}")
            confirm = typer.confirm("是否执行？", default=True)
            if confirm:
                completed = subprocess.run(step, shell=True)
                _record_command_usage(step, getattr(completed, "returncode", None))
            else:
                typer.echo("⏭️  跳过该步骤")
    except Exception as e:
        typer.echo(f"❌ 执行工作流失败: {str(e)}", err=True)

@app.command()
def clear(force: bool = False):
    """清空所有记忆"""
    if not force:
        confirm = typer.confirm("确定要清空所有记忆吗？此操作不可恢复！")
        if not confirm:
            return

    try:
        response = _request("DELETE", "/memory/")
        response.raise_for_status()
        result = response.json()
        deleted_count = result.get("deleted_count", 0)
        typer.echo(f"✅ {result.get('message', f'已清空 {deleted_count} 条记忆')}")
    except requests.RequestException as e:
        typer.echo(f"❌ 清空失败: {str(e)}", err=True)
    except Exception as e:
        typer.echo(f"❌ 清空失败: {str(e)}", err=True)

if __name__ == "__main__":
    app()
