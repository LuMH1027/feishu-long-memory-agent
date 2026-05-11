#!/usr/bin/env python3
"""冒烟测试调试版 — 每个断点捕获完整堆栈和响应体，输出到 smoke_debug.log"""

import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
LOG_PATH = WORKSPACE / "scripts" / "smoke_debug.log"


def main():
    with open(LOG_PATH, "w", encoding="utf-8") as log:
        log.write(f"=== 冒烟测试调试日志 ===\n")
        log.write(f"时间: {datetime.now().isoformat()}\n")
        log.write(f"Python: {sys.version}\n\n")

        # 1. 启动后端
        log.write("--- 启动后端 ---\n")
        log.flush()
        backend = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.main:app",
             "--host", "127.0.0.1", "--port", "8000"],
            cwd=WORKSPACE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )

        import time, requests
        for i in range(15):
            try:
                r = requests.get("http://127.0.0.1:8000/health/", timeout=2)
                if r.status_code == 200:
                    log.write(f"后端已就绪 (attempt {i+1})\n")
                    break
            except Exception:
                time.sleep(1)
        else:
            log.write("后端启动超时\n")
            backend.terminate()
            return

        # 2. 逐个测试断点
        API = "http://127.0.0.1:8000/api/v1"

        def do(method: str, path: str, label: str, **kwargs):
            """执行一个请求，记录完整信息"""
            log.write(f"\n{'='*60}\n")
            log.write(f"  {label}\n")
            log.write(f"  {method} {path}\n")
            log.write(f"{'='*60}\n")
            if "json" in kwargs:
                import json as j
                log.write(f"  REQUEST BODY:\n{j.dumps(kwargs['json'], ensure_ascii=False, indent=2)}\n")
            if "params" in kwargs:
                log.write(f"  PARAMS: {kwargs['params']}\n")

            try:
                r = requests.request(method, f"{API}{path}", timeout=15, **kwargs)
                log.write(f"  STATUS: {r.status_code}\n")
                log.write(f"  HEADERS: {dict(r.headers)}\n")
                try:
                    body = r.json()
                    import json as j
                    log.write(f"  RESPONSE:\n{j.dumps(body, ensure_ascii=False, indent=2)}\n")
                except Exception:
                    log.write(f"  RESPONSE TEXT: {r.text[:2000]}\n")
                return r
            except Exception as e:
                log.write(f"  EXCEPTION: {type(e).__name__}: {e}\n")
                traceback.print_exc(file=log)
                return None

        # ── Test 1: trash ──
        # 先创建一条记忆，再删除它
        r = do("POST", "/memory/", "Create memory for trash test",
               json={"content": "trash_test_command", "type": "cli_command", "source": "cli"})
        mem_id = r.json().get("id", "") if r and r.status_code == 200 else ""

        r = do("DELETE", f"/memory/{mem_id}", "Soft delete the memory")
        r = do("GET", "/memory/trash", "List trash")

        # 恢复
        r = do("POST", f"/memory/{mem_id}/restore", "Restore from trash")

        # ── Test 2: pending decision ──
        r = do("POST", "/feishu/message/analyze", "Create pending decision #1",
               json={"content": "以后后端统一用 Go，不再使用 Python",
                     "chat_id": "debug_chat", "user_id": "debug_user"})
        log.write(f"\n  RAW RESPONSE KEYS: {list(r.json().keys()) if r and r.status_code == 200 else 'N/A'}\n")

        r = do("GET", "/feishu/decisions/recent", "Fetch recent decisions",
               params={"limit": 10})

        # ── Test 3: search all memories of type project_decision ──
        r = do("GET", "/memory/list", "List all memories", params={"limit": 200})
        if r and r.status_code == 200:
            all_mems = r.json()
            log.write(f"\n  Total memories: {len(all_mems)}\n")
            project_decisions = [m for m in all_mems if m.get("type") == "project_decision"]
            log.write(f"  project_decision count: {len(project_decisions)}\n")
            for m in project_decisions[:10]:
                meta = m.get("metadata", {})
                log.write(f"    id={m['id'][:12]} type={m.get('type')} "
                          f"status_in_meta={meta.get('status','MISSING')} "
                          f"topic={meta.get('topic','?')[:30]}\n")

        # ── Test 4: event callback ──
        r = do("POST", "/feishu/event/callback", "URL verification",
               json={"type": "url_verification", "token": "t", "challenge": "test_challenge"})

        r = do("POST", "/feishu/event/callback", "Message callback",
               json={"schema": "2.0", "header": {"event_type": "im.message.receive_v1"},
                     "event": {"message": {"message_id": "om_test", "chat_id": "oc_test",
                                           "content": '{"text":"test"}', "mentions": [{"name": "bot"}]},
                               "sender": {"sender_id": {"user_id": "test_user"}}}})

        # ── Test 5: CLI search timeout ──
        log.write("\n--- CLI search 测试 ---\n")
        import time as t
        start = t.perf_counter()
        try:
            result = subprocess.run(
                [sys.executable, "-m", "cli.main", "search", "docker", "--limit", "3"],
                capture_output=True, text=True, timeout=30, cwd=WORKSPACE,
            )
            elapsed = t.perf_counter() - start
            log.write(f"  Exit code: {result.returncode}\n")
            log.write(f"  Time: {elapsed:.2f}s\n")
            log.write(f"  STDOUT:\n{result.stdout[:1000]}\n")
            if result.stderr:
                log.write(f"  STDERR:\n{result.stderr[:1000]}\n")
        except subprocess.TimeoutExpired:
            log.write(f"  TIMEOUT after 30s\n")
        except Exception as e:
            log.write(f"  EXCEPTION: {traceback.format_exc()}\n")

        log.write(f"\n=== 完成 ===\n")
        backend.terminate()
        backend.wait(timeout=5)

    print(f"调试日志已保存: {LOG_PATH}")


if __name__ == "__main__":
    main()
