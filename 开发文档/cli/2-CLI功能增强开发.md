# 阶段2：CLI功能增强开发
## 开发目标
完善CLI端功能，实现交互式搜索、自动命令捕获、工作流管理三个核心功能

## 修改文件
`cli/main.py`

---

## 2.1 增强`search`命令的交互体验
### 功能说明
搜索结果支持一键复制、直接执行、交互式选择

### 代码实现
```python
import pyperclip
import subprocess

@app.command()
def search(
    query: str = typer.Argument(..., help="搜索关键词"),
    limit: int = typer.Option(5, help="返回结果数量"),
    execute: bool = typer.Option(False, help="直接执行第一个匹配的命令"),
    copy: bool = typer.Option(False, help="直接复制第一个匹配的命令到剪贴板"),
    type: str = typer.Option(None, help="按记忆类型过滤")
):
    """搜索相关记忆"""
    params = {"query": query, "limit": limit}
    if type:
        params["type"] = type
    
    response = requests.get(
        f"{get_api_base()}/memory/search",
        params=params
    )
    response.raise_for_status()
    results = response.json()
    
    if not results:
        typer.echo("❌ 没有找到相关记忆")
        return
    
    if execute:
        cmd = results[0]["content"]
        typer.echo(f"🚀 执行命令：{cmd}")
        subprocess.run(cmd, shell=True)
        return
    
    if copy:
        cmd = results[0]["content"]
        pyperclip.copy(cmd)
        typer.echo(f"✅ 已复制到剪贴板：{cmd}")
        return
    
    # 交互式选择
    typer.echo("找到以下相关命令：")
    for i, result in enumerate(results, 1):
        typer.echo(f"\n{i}. {result['content']}")
        typer.echo(f"   描述：{result.get('description', '无描述')}")
        typer.echo(f"   使用次数：{result.get('metadata', {}).get('count', 0)}")
    
    selected = typer.prompt("\n请选择要执行/复制的命令序号（输入0退出）", type=int, default=0)
    if selected > 0 and selected <= len(results):
        cmd = results[selected-1]["content"]
        action = typer.prompt("请选择操作：1=执行 2=复制", type=int, default=1)
        if action == 1:
            subprocess.run(cmd, shell=True)
        else:
            pyperclip.copy(cmd)
            typer.echo("✅ 已复制到剪贴板")
```

### 测试用例
```powershell
# 1. 先手动存一个测试命令
mem memorize "echo test command" --type "cli_command"

# 2. 测试直接复制功能
mem search "test" --copy
# 预期输出：✅ 已复制到剪贴板：echo test command
# 验证：剪贴板内容应该为"echo test command"

# 3. 测试直接执行功能
mem search "test" --execute
# 预期输出：
# 🚀 执行命令：echo test command
# test command

# 4. 测试交互式选择
mem search "test"
# 预期输出：列出匹配结果，提示选择序号，选择后可以执行或复制
```

---

## 2.2 实现`watch`命令，自动捕获历史命令
### 功能说明
扫描shell历史记录，自动记录高频使用的命令

### 代码实现
```python
from pathlib import Path
from collections import Counter

@app.command()
def watch(
    shell: str = typer.Option("powershell", help="要监控的shell类型：powershell/bash/zsh"),
    auto_record_threshold: int = typer.Option(3, help="命令使用多少次后自动记录")
):
    """开启命令行监控模式，自动记录高频命令"""
    history_file = {
        "powershell": Path.home() / "AppData/Roaming/Microsoft/Windows/PowerShell/PSReadLine/ConsoleHost_history.txt",
        "bash": Path.home() / ".bash_history",
        "zsh": Path.home() / ".zsh_history"
    }[shell]
    
    # 读取历史命令统计频率
    with open(history_file, "r", encoding="utf-8", errors="ignore") as f:
        commands = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    
    command_counts = Counter(commands)
    
    # 自动记录使用超过阈值的命令
    recorded_count = 0
    for cmd, count in command_counts.items():
        if count >= auto_record_threshold and len(cmd) > 10: # 过滤短命令
            # 调用后端API存入记忆
            try:
                requests.post(
                    f"{get_api_base()}/cli/command/record",
                    json={"command": cmd, "count": count, "shell": shell}
                )
                recorded_count += 1
            except:
                pass
    
    typer.echo(f"✅ 已扫描历史命令，自动记录了{recorded_count}条高频命令")
```

### 测试用例
```powershell
# 1. 执行3次测试命令（触发自动记录阈值）
echo "test watch command"
echo "test watch command"
echo "test watch command"

# 2. 运行watch命令
mem watch --shell powershell --auto-record-threshold 3
# 预期输出：✅ 已扫描历史命令，自动记录了X条高频命令

# 3. 验证自动记录的命令
mem search "test watch command"
# 预期输出：能找到刚才自动记录的命令
```

---

## 2.3 新增`workflow`工作流命令组
### 功能说明
支持多步骤工作流的存储和一键执行

### 代码实现
```python
import json
from datetime import datetime

workflow_app = typer.Typer(help="工作流模板管理")
app.add_typer(workflow_app, name="workflow")

@workflow_app.command("save")
def save_workflow(
    name: str = typer.Argument(..., help="工作流名称"),
    steps: List[str] = typer.Argument(..., help="工作流步骤命令，用空格分隔，多词用引号包裹")
):
    """保存工作流模板"""
    workflow = {
        "name": name,
        "steps": steps,
        "created_at": datetime.now().isoformat()
    }
    response = requests.post(
        f"{get_api_base()}/memory/",
        json={
            "content": json.dumps(workflow, ensure_ascii=False),
            "type": "cli_workflow",
            "description": f"工作流：{name}",
            "metadata": workflow
        }
    )
    response.raise_for_status()
    typer.echo(f"✅ 工作流「{name}」已保存，包含{len(steps)}个步骤")

@workflow_app.command("run")
def run_workflow(name: str = typer.Argument(..., help="工作流名称")):
    """执行已保存的工作流"""
    response = requests.get(
        f"{get_api_base()}/memory/search",
        params={"query": name, "type": "cli_workflow", "limit": 1}
    )
    results = response.json()
    if not results:
        typer.echo(f"❌ 未找到工作流「{name}」")
        return
    
    workflow = json.loads(results[0]["content"])
    typer.echo(f"🚀 开始执行工作流「{name}」，共{len(workflow['steps'])}个步骤")
    
    for i, step in enumerate(workflow["steps"], 1):
        typer.echo(f"\n步骤 {i}/{len(workflow['steps'])}: {step}")
        confirm = typer.confirm("是否执行？", default=True)
        if confirm:
            subprocess.run(step, shell=True)
        else:
            typer.echo("⏭️  跳过该步骤")
```

### 测试用例
```powershell
# 1. 保存一个测试工作流
mem workflow save "测试工作流" "echo step1" "echo step2" "echo step3"
# 预期输出：✅ 工作流「测试工作流」已保存，包含3个步骤

# 2. 查看是否保存成功
mem search "测试工作流" --type "cli_workflow"
# 预期输出：能找到刚才保存的工作流

# 3. 执行工作流（全部选跳过）
mem workflow run "测试工作流"
# 预期输出：
# 🚀 开始执行工作流「测试工作流」，共3个步骤
# 步骤 1/3: echo step1
# 是否执行？ [Y/n] n
# ⏭️  跳过该步骤
# ...（依次跳过所有步骤）
```

## 完成标准
✅ 三个功能都能正常运行，测试用例全部通过
