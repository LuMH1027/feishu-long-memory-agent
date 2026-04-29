import os
import subprocess
from typing import Any, Optional


def send_text_message(
    chat_id: str,
    text: str,
    *,
    cli_bin: Optional[str] = None,
    timeout: Optional[int] = None,
) -> dict[str, Any]:
    """使用官方 larksuite/cli 发送飞书群文本消息。"""
    command = [
        cli_bin or os.getenv("LARK_CLI_BIN", "lark-cli"),
        "im",
        "+messages-send",
        "--as",
        "bot",
        "--chat-id",
        chat_id,
        "--text",
        text,
        "--format",
        "json",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout or int(os.getenv("LARK_CLI_TIMEOUT_SECONDS", "15")),
            check=False,
        )
    except FileNotFoundError:
        return {
            "status": "error",
            "provider": "lark-cli",
            "message": "未找到 lark-cli，请先安装并完成 lark-cli config init/auth",
            "command": command,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "provider": "lark-cli",
            "message": "lark-cli 调用超时",
            "command": command,
        }

    return {
        "status": "ok" if completed.returncode == 0 else "error",
        "provider": "lark-cli",
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "command": command,
    }
