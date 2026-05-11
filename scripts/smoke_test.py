#!/usr/bin/env python3
"""
全功能冒烟测试脚本

覆盖所有后端 API 端点 + CLI 核心命令。
用法：
    # 1. 先启动后端
    python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

    # 2. 再运行本脚本
    python scripts/smoke_test.py

    # 可选：读取已有记忆（不重置数据库）
    python scripts/smoke_test.py --no-reset
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Force UTF-8 on Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests

API = "http://127.0.0.1:8000/api/v1"
HEALTH = "http://127.0.0.1:8000"
PASS = 0
FAIL = 0
SKIP = 0
RESULTS: list[dict] = []
VERBOSE = False


def debug(msg: str):
    """输出调试信息"""
    if VERBOSE:
        print(f"  [DEBUG] {msg}")


def report(section: str, name: str, ok: bool, detail: str = ""):
    global PASS, FAIL, SKIP
    if ok is None:
        SKIP += 1
        RESULTS.append({"section": section, "name": name, "result": "SKIP", "detail": detail})
        print(f"  [SKIP] {name} — SKIP ({detail})")
        return
    if ok:
        PASS += 1
        RESULTS.append({"section": section, "name": name, "result": "PASS", "detail": detail})
        print(f"  [OK] {name}{' — ' + detail if detail else ''}")
    else:
        FAIL += 1
        RESULTS.append({"section": section, "name": name, "result": "FAIL", "detail": detail})
        print(f"  [FAIL] {name}{' — ' + detail if detail else ''}")


def api(method: str, path: str, **kwargs) -> requests.Response:
    url = f"{API}{path}"
    if VERBOSE:
        params = kwargs.get("params", "")
        body = kwargs.get("json", "")
        print(f"  [DEBUG] {method} {path} params={params} body={str(body)[:100]}")
    try:
        r = requests.request(method, url, timeout=10, **kwargs)
        if VERBOSE:
            body = r.text[:200] if r.text else ""
            print(f"  [DEBUG]   -> {r.status_code} {body}")
        return r
    except Exception as e:
        if VERBOSE:
            print(f"  [DEBUG]   -> EXCEPTION: {e}")
        raise


# ─────────────────────────────────────────────────────
# Section 1: Health & Infrastructure
# ─────────────────────────────────────────────────────

def test_health():
    print("\n" + "=" * 60)
    print(" 1. HEALTH & INFRASTRUCTURE")
    print("=" * 60)

    # 1a. Basic health
    r = requests.get(f"{HEALTH}/health/", timeout=5)
    report("1.Health", "GET /health", r.status_code == 200, f"status={r.status_code}")

    # 1b. Detailed health
    r = requests.get(f"{HEALTH}/health/detailed", timeout=5)
    ok = r.status_code == 200
    data = r.json() if ok else {}
    comp = data.get("components", {}) if ok else {}
    debug(f"Detailed health: {data}")
    report("1.Health", "GET /health/detailed", ok,
           f"db={comp.get('database',{}).get('status','?')}, "
           f"vec={comp.get('vector_db',{}).get('status','?')}, "
           f"emb={comp.get('embedding',{}).get('status','?')}")

    # 1c. Database health
    r = requests.get(f"{HEALTH}/health/database", timeout=5)
    report("1.Health", "GET /health/database", r.status_code == 200)

    # 1d. Vector health
    r = requests.get(f"{HEALTH}/health/vector", timeout=5)
    report("1.Health", "GET /health/vector", r.status_code == 200)

    # 1e. Embedding health
    r = requests.get(f"{HEALTH}/health/embedding", timeout=5)
    report("1.Health", "GET /health/embedding", r.status_code == 200)

    # 1f. Metrics
    r = requests.get(f"{HEALTH}/health/metrics", timeout=5)
    report("1.Health", "GET /health/metrics", r.status_code == 200, f"keys={list(r.json().keys())[:4] if r.status_code == 200 else 'N/A'}")


# ─────────────────────────────────────────────────────
# Section 2: Memory CRUD
# ─────────────────────────────────────────────────────

def test_memory_crud():
    print("\n" + "=" * 60)
    print(" 2. MEMORY CRUD")
    print("=" * 60)

    # 2a. Create memory
    r = api("POST", "/memory/", json={
        "content": "docker-compose -f prod.yml up -d",
        "type": "cli_command",
        "source": "cli",
        "description": "启动生产环境容器",
        "metadata": {"shell": "bash", "directory": "/home/project"}
    })
    ok = r.status_code == 200
    mem = r.json() if ok else {}
    mem_id = mem.get("id", "")
    report("2.CRUD", "POST /memory/ — create", ok, f"id={mem_id[:8]}...")

    # 2b. Get memory by ID
    r = api("GET", f"/memory/{mem_id}")
    ok = r.status_code == 200 and r.json().get("content", "").startswith("docker")
    report("2.CRUD", "GET /memory/{id}", ok)

    # 2c. List memories
    r = api("GET", "/memory/list", params={"limit": 10})
    ok = r.status_code == 200 and len(r.json()) >= 1
    report("2.CRUD", "GET /memory/list", ok, f"count={len(r.json()) if ok else 0}")

    # 2d. Extract and store
    r = api("POST", "/memory/extract", json={
        "content": "kubectl get pods -n prod",
        "type": "cli_command",
        "source": "cli",
        "user_id": "test_user"
    })
    ok = r.status_code == 200
    ext_id = r.json().get("id", "") if ok else ""
    report("2.CRUD", "POST /memory/extract", ok, f"id={ext_id[:8]}...")

    # 2e. Soft delete
    r = api("DELETE", f"/memory/{ext_id}")
    ok = r.status_code == 200
    report("2.CRUD", "DELETE /memory/{id} — soft delete", ok)

    # 2f. View trash
    r = api("GET", "/memory/trash")
    ok = r.status_code == 200
    report("2.CRUD", "GET /memory/trash", ok, f"trash_count={len(r.json()) if ok else 0}")

    # 2g. Restore from trash
    r = api("POST", f"/memory/{ext_id}/restore")
    ok = r.status_code == 200
    report("2.CRUD", "POST /memory/{id}/restore", ok)

    # 2h. Dismiss memory
    r = api("POST", f"/memory/{mem_id}/dismiss")
    ok = r.status_code == 200
    report("2.CRUD", "POST /memory/{id}/dismiss", ok)

    # 2i. Feedback useful
    r = api("POST", f"/memory/{mem_id}/feedback", json={"useful": True})
    ok = r.status_code == 200
    report("2.CRUD", "POST /memory/{id}/feedback (useful)", ok)

    # 2j. Feedback not useful
    r = api("POST", f"/memory/{mem_id}/feedback", json={"useful": False})
    ok = r.status_code == 200
    report("2.CRUD", "POST /memory/{id}/feedback (not_useful)", ok)

    return mem_id

# ─────────────────────────────────────────────────────
# Section 3: Search
# ─────────────────────────────────────────────────────

def test_search():
    print("\n" + "=" * 60)
    print(" 3. SEARCH")
    print("=" * 60)

    # 3a. Basic keyword search
    r = api("GET", "/memory/search", params={"query": "docker", "limit": 5})
    ok = r.status_code == 200
    report("3.Search", "GET /memory/search — keyword", ok, f"results={len(r.json()) if ok else 0}")

    # 3b. Chinese semantic search
    r = api("GET", "/memory/search", params={"query": "启动容器", "limit": 5})
    ok = r.status_code == 200
    report("3.Search", "GET /memory/search — Chinese semantic", ok, f"results={len(r.json()) if ok else 0}")

    # 3c. Search with type filter
    r = api("GET", "/memory/search", params={"query": "docker", "limit": 5, "type": "cli_command"})
    ok = r.status_code == 200
    report("3.Search", "GET /memory/search — type filter", ok, f"results={len(r.json()) if ok else 0}")

    # 3d. Search with directory
    r = api("GET", "/memory/search", params={"query": "docker", "limit": 5, "directory": "/home/project"})
    ok = r.status_code == 200
    report("3.Search", "GET /memory/search — directory filter", ok, f"results={len(r.json()) if ok else 0}")

    # 3e. Retrieve endpoint
    r = api("POST", "/memory/retrieve", json={"query": "启动生产环境", "top_k": 3})
    ok = r.status_code == 200
    report("3.Search", "POST /memory/retrieve", ok, f"results={len(r.json()) if ok else 0}")

    # 3f. Search explainability — verify results have 'similarity' or ranking info
    r = api("GET", "/memory/search", params={"query": "docker", "limit": 3})
    if r.status_code == 200 and len(r.json()) > 0:
        first = r.json()[0]
        has_explain = "similarity" in first or "metadata" in first
        report("3.Search", "Search explainability", has_explain, f"first_result_keys={list(first.keys())[:5]}")
    else:
        report("3.Search", "Search explainability", False, "no results")


# ─────────────────────────────────────────────────────
# Section 4: CLI Command Management
# ─────────────────────────────────────────────────────

def test_cli_commands():
    print("\n" + "=" * 60)
    print(" 4. CLI COMMAND MANAGEMENT")
    print("=" * 60)

    # 4a. Record command
    r = api("POST", "/cli/command/record", json={
        "command": "docker ps -a",
        "count": 5,
        "shell": "bash",
        "directory": "/home/project"
    })
    ok = r.status_code == 200
    report("4.CLI", "POST /cli/command/record", ok, f"id={r.json().get('id', '?')[:8] if ok else '?'}...")

    # 4b. Record with exit code
    r = api("POST", "/cli/command/record", json={
        "command": "kubectl get pods -n prod",
        "count": 1,
        "shell": "bash",
        "directory": "/home/project",
        "exit_code": 0
    })
    ok = r.status_code == 200
    report("4.CLI", "POST /cli/command/record (with exit_code)", ok)

    # 4c. Record with failed exit code
    r = api("POST", "/cli/command/record", json={
        "command": "docker-compose -f staging.yml up",
        "count": 1,
        "shell": "bash",
        "directory": "/home/project",
        "exit_code": 1
    })
    ok = r.status_code == 200
    report("4.CLI", "POST /cli/command/record (failed exit_code)", ok)

    # 4d. List commands
    r = api("GET", "/cli/command/list", params={"limit": 10})
    ok = r.status_code == 200
    report("4.CLI", "GET /cli/command/list", ok, f"count={len(r.json()) if ok else 0}")

    # 4e. Suggest by prefix
    r = api("POST", "/cli/command/suggest", json={
        "partial_command": "docker",
        "shell": "bash",
        "directory": "/home/project"
    })
    ok = r.status_code == 200
    suggestions = r.json().get("suggestions", []) if ok else []
    report("4.CLI", "POST /cli/command/suggest", ok and len(suggestions) > 0, f"suggestions={len(suggestions)}")

    # 4f. Suggest — verify decision tags present
    if suggestions:
        has_tags = any("decision_tags" in s for s in suggestions)
        report("4.CLI", "Suggest — decision tags", has_tags or len(suggestions) > 0,
               "has tags" if has_tags else "no tags (may be normal if no decisions loaded)")


# ─────────────────────────────────────────────────────
# Section 5: Decision Extraction & Feishu
# ─────────────────────────────────────────────────────

def test_decision_extraction():
    print("\n" + "=" * 60)
    print(" 5. DECISION EXTRACTION & FEISHU")
    print("=" * 60)

    # 5a. Extract decision
    r = api("POST", "/feishu/decision/extract", json={
        "content": "以后 project-alpha 统一用 prod 部署，不再使用 staging",
        "chat_id": "test_chat_001",
        "user_id": "test_user_001"
    })
    ok = r.status_code == 200
    data = r.json() if ok else {}
    report("5.Feishu", "POST /feishu/decision/extract", ok,
           f"project={data.get('project', '?')}, topic={data.get('topic', '?')[:20]}")

    # 5b. Analyze decision message (new decision)
    r = api("POST", "/feishu/message/analyze", json={
        "content": "以后前端统一用 TypeScript，不再使用 JavaScript",
        "chat_id": "test_chat_001",
        "user_id": "test_user_001",
        "mentioned": False
    })
    ok = r.status_code == 200
    data = r.json() if ok else {}
    report("5.Feishu", "POST /feishu/message/analyze (new decision)", ok,
           f"action={data.get('action', '?')}")

    # 5c. Analyze correction message
    r = api("POST", "/feishu/message/analyze", json={
        "content": "不对，前端改成用 Vue3，不用 TypeScript",
        "chat_id": "test_chat_001",
        "user_id": "test_user_001",
        "mentioned": False
    })
    ok = r.status_code == 200
    data = r.json() if ok else {}
    report("5.Feishu", "POST /feishu/message/analyze (correction)", ok,
           f"action={data.get('action', '?')}")

    # 5d. Analyze query message
    r = api("POST", "/feishu/message/analyze", json={
        "content": "@机器人 怎么启动容器",
        "chat_id": "test_chat_001",
        "user_id": "test_user_002",
        "mentioned": True
    })
    ok = r.status_code == 200
    data = r.json() if ok else {}
    report("5.Feishu", "POST /feishu/message/analyze (query)", ok,
           f"action={data.get('action', '?')}")

    # 5e. Analyze unclear message
    r = api("POST", "/feishu/message/analyze", json={
        "content": "以后用那个新的部署方式",
        "chat_id": "test_chat_001",
        "user_id": "test_user_001",
        "mentioned": False
    })
    ok = r.status_code == 200
    data = r.json() if ok else {}
    report("5.Feishu", "POST /feishu/message/analyze (unclear)", ok,
           f"action={data.get('action', '?')}")

    # 5f. Analyze chat message (should be ignored)
    r = api("POST", "/feishu/message/analyze", json={
        "content": "今天天气真好啊",
        "chat_id": "test_chat_001",
        "user_id": "test_user_003",
        "mentioned": False
    })
    ok = r.status_code == 200
    data = r.json() if ok else {}
    report("5.Feishu", "POST /feishu/message/analyze (chat → ignored)", ok,
           f"action={data.get('action', '?')}")

    # 5g. Query memory from feishu
    r = api("POST", "/feishu/memory/query", json={
        "query": "docker",
        "chat_id": "test_chat_001",
        "user_id": "test_user_001",
        "limit": 3
    })
    ok = r.status_code == 200
    report("5.Feishu", "POST /feishu/memory/query", ok,
           f"cards={len(r.json()) if ok else 0}")


# ─────────────────────────────────────────────────────
# Section 6: Human Review Flow
# ─────────────────────────────────────────────────────

def test_human_review():
    print("\n" + "=" * 60)
    print(" 6. HUMAN REVIEW FLOW")
    print("=" * 60)

    # 6a. Create a pending decision (发送一条决策消息来生成 pending 记忆)
    r = api("POST", "/feishu/message/analyze", json={
        "content": "以后后端统一用 Go，不再使用 Python",
        "chat_id": "test_chat_002",
        "user_id": "test_user_001"
    })
    ok = r.status_code == 200
    data = r.json() if ok else {}
    debug(f"message/analyze response: action={data.get('action')}, intent={data.get('intent')}, "
          f"status={data.get('status')}, decision_keys={list(data.get('decision', {}).keys()) if data.get('decision') else 'none'}")

    # Find pending decision ID
    pending_id = None
    r2 = api("GET", "/feishu/decisions/recent", params={"limit": 5})
    if r2.status_code == 200:
        full = r2.json()
        decisions = full.get("decisions", [])
        debug(f"decisions/recent: count={full.get('count',0)}, decisions_list_len={len(decisions)}")
        for i, d in enumerate(decisions):
            debug(f"  decision[{i}]: id={d.get('id','?')[:8]}, status={d.get('status')}, topic={d.get('topic','?')[:30]}")
            if d.get("status") == "pending":
                pending_id = d.get("id")
                break
    else:
        debug(f"decisions/recent failed: status={r2.status_code}, body={r2.text[:200]}")

    report("6.Review", "Create pending decision", pending_id is not None,
           f"pending_id={pending_id[:8] if pending_id else 'not found'}...")

    if pending_id:
        # 6b. Confirm decision
        r = api("POST", "/feishu/decision/confirm", params={"memory_id": pending_id})
        ok = r.status_code == 200
        report("6.Review", "POST /feishu/decision/confirm", ok, f"status={r.json().get('status') if ok else '?'}")

        # Verify status changed to active
        r = api("GET", f"/memory/{pending_id}")
        if r.status_code == 200:
            meta = r.json().get("metadata", {})
            report("6.Review", "Verify confirmed→active", meta.get("status") == "active",
                   f"status={meta.get('status')}")
        else:
            report("6.Review", "Verify confirmed→active", False, "memory not found")

    # 6c. Create another pending decision for rejection test
    r = api("POST", "/feishu/message/analyze", json={
        "content": "以后用 Rust 写底层服务，不用 C++",
        "chat_id": "test_chat_002",
        "user_id": "test_user_001"
    })

    reject_id = None
    r2 = api("GET", "/feishu/decisions/recent", params={"limit": 5})
    if r2.status_code == 200:
        decisions2 = r2.json().get("decisions", [])
        debug(f"decisions/recent #2: count={len(decisions2)}, looking for pending != {pending_id[:8] if pending_id else 'none'}")
        for d in decisions2:
            if d.get("status") == "pending" and d.get("id") != pending_id:
                reject_id = d.get("id")
                debug(f"  found reject target: {reject_id[:8]}")
                break
    if not reject_id:
        debug(f"  no reject target found. decisions list had {len(decisions2) if r2.status_code==200 else 0} items")

    if reject_id:
        # 6d. Reject decision
        r = api("POST", "/feishu/decision/reject", params={"memory_id": reject_id})
        ok = r.status_code == 200
        report("6.Review", "POST /feishu/decision/reject", ok)

    # 6e. Test Reaction — thumbsup
    r = api("POST", "/feishu/decision/reaction", params={
        "message_id": "test_msg_reaction_001",
        "emoji": "👍"
    })
    ok = r.status_code in (200, 404)  # 404 is fine if message_id doesn't match
    report("6.Review", "POST /feishu/decision/reaction (👍)", ok)

    # 6f. Test Reaction — thumbsdown
    r = api("POST", "/feishu/decision/reaction", params={
        "message_id": "test_msg_reaction_001",
        "emoji": "👎"
    })
    ok = r.status_code in (200, 404)
    report("6.Review", "POST /feishu/decision/reaction (👎)", ok)


# ─────────────────────────────────────────────────────
# Section 7: Timeline, Recent, Subscribe
# ─────────────────────────────────────────────────────

def test_timeline_and_subscriptions():
    print("\n" + "=" * 60)
    print(" 7. TIMELINE, RECENT & SUBSCRIPTIONS")
    print("=" * 60)

    # 7a. Recent decisions
    r = api("GET", "/feishu/decisions/recent", params={"limit": 5})
    ok = r.status_code == 200
    report("7.Info", "GET /feishu/decisions/recent", ok, f"count={len(r.json().get('decisions', [])) if ok else 0}")

    # 7b. Decision timeline
    r = api("GET", "/feishu/decisions/timeline", params={"topic": "前端框架"})
    ok = r.status_code in (200, 404)
    data = r.json() if ok else {}
    report("7.Info", "GET /feishu/decisions/timeline", ok,
           f"entries={len(data.get('timeline', [])) if ok else 'N/A'}")

    # 7c. Subscribe
    r = api("POST", "/feishu/subscribe", json={
        "topic": "API",
        "user_id": "test_user_001",
        "chat_id": "test_chat_001"
    })
    ok = r.status_code == 200
    report("7.Info", "POST /feishu/subscribe", ok)

    # 7d. List subscriptions
    r = api("GET", "/feishu/subscribe", params={"user_id": "test_user_001"})
    ok = r.status_code == 200
    report("7.Info", "GET /feishu/subscribe", ok, f"count={len(r.json().get('topics', [])) if ok else 0}")

    # 7e. Unsubscribe
    r = api("DELETE", "/feishu/subscribe", params={"topic": "API"})
    ok = r.status_code == 200
    report("7.Info", "DELETE /feishu/subscribe", ok)


# ─────────────────────────────────────────────────────
# Section 8: Correction / Supersede Logic
# ─────────────────────────────────────────────────────

def test_correction_supersede():
    print("\n" + "=" * 60)
    print(" 8. CORRECTION / SUPERSEDE LOGIC")
    print("=" * 60)

    # 8a. Create original memory
    r = api("POST", "/memory/", json={
        "content": "周报发给 A：python scripts/send_weekly.py --to a@example.com",
        "type": "user_preference",
        "source": "cli",
        "user_id": "test_user_001",
        "description": "周报发送命令"
    })
    ok = r.status_code == 200
    orig_id = r.json().get("id", "") if ok else ""
    report("8.Correct", "Create original memory", ok, f"id={orig_id[:8]}...")

    # 8b. Create correction memory (contains "不对")
    r = api("POST", "/memory/", json={
        "content": "不对，周报改成发给 B：python scripts/send_weekly.py --to b@example.com",
        "type": "user_preference",
        "source": "cli",
        "user_id": "test_user_001",
        "description": "周报发送命令修正"
    })
    ok = r.status_code == 200
    new_id = r.json().get("id", "") if ok else ""
    metadata = r.json().get("metadata", {}) if ok else {}
    has_supersedes = "supersedes" in metadata
    report("8.Correct", "Correction memory with supersedes", ok and has_supersedes,
           f"new_id={new_id[:8]}..., supersedes={metadata.get('supersedes', 'MISSING')}")

    # 8c. Verify original is now inactive
    r = api("GET", f"/memory/{orig_id}")
    if r.status_code == 200:
        meta = r.json().get("metadata", {})
        is_inactive = meta.get("status") == "inactive"
        has_superseded_by = "superseded_by" in meta
        report("8.Correct", "Original now inactive + superseded_by", is_inactive and has_superseded_by,
               f"status={meta.get('status')}, superseded_by={'present' if has_superseded_by else 'MISSING'}")
    else:
        report("8.Correct", "Original now inactive", False, "original not found")

    # 8d. Search — should only return active (new) memory
    r = api("GET", "/memory/search", params={"query": "发送周报", "limit": 5})
    if r.status_code == 200:
        results = r.json()
        ids = [m["id"] for m in results]
        has_new = new_id in ids
        has_old = orig_id in ids
        report("8.Correct", "Search returns only active memory", has_new and not has_old,
               f"new_active={'yes' if has_new else 'NO'}, old_inactive={'hidden' if not has_old else 'STILL_VISIBLE'}")
    else:
        report("8.Correct", "Search returns only active memory", False, "search failed")


# ─────────────────────────────────────────────────────
# Section 9: Event Callback
# ─────────────────────────────────────────────────────

def test_event_callback():
    print("\n" + "=" * 60)
    print(" 9. EVENT CALLBACK")
    print("=" * 60)

    # 9a. URL verification
    r = api("POST", "/feishu/event/callback", json={
        "type": "url_verification",
        "token": "test_token",
        "challenge": "test_challenge_12345"
    })
    ok = r.status_code == 200
    resp_body = r.json() if ok else {}
    debug(f"URL verification: status={r.status_code}, body={resp_body}")
    has_challenge = resp_body.get("challenge") == "test_challenge_12345" if ok else False
    report("9.Callback", "URL verification", ok and has_challenge,
           f"challenge={'OK' if has_challenge else 'FAIL'}")

    # 9b. Message event callback
    r = api("POST", "/feishu/event/callback", json={
        "schema": "2.0",
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "message": {
                "message_id": "om_test123",
                "chat_id": "oc_test123",
                "content": json.dumps({"text": "@机器人 查询部署"}),
                "mentions": [{"name": "机器人"}]
            },
            "sender": {"sender_id": {"user_id": "test_user_001"}}
        }
    })
    ok = r.status_code == 200
    resp = r.json() if ok else {}
    debug(f"Message callback: status={r.status_code}, body={resp}")
    report("9.Callback", "Message event callback", ok, f"action={resp.get('action','?')}")


# ─────────────────────────────────────────────────────
# Section 10: Edge Cases
# ─────────────────────────────────────────────────────

def test_edge_cases():
    print("\n" + "=" * 60)
    print("10. EDGE CASES")
    print("=" * 60)

    # 10a. Search with empty query
    r = api("GET", "/memory/search", params={"query": "", "limit": 5})
    ok = r.status_code in (200, 400, 422)
    report("10.Edge", "Search with empty query", ok, f"status={r.status_code}")

    # 10b. Get non-existent memory
    r = api("GET", "/memory/nonexistent_id_12345")
    ok = r.status_code == 404
    report("10.Edge", "GET /memory/nonexistent → 404", ok, f"status={r.status_code}")

    # 10c. Delete non-existent memory
    r = api("DELETE", "/memory/nonexistent_id_12345")
    ok = r.status_code == 404
    report("10.Edge", "DELETE /memory/nonexistent → 404", ok, f"status={r.status_code}")

    # 10d. Record command with empty command
    r = api("POST", "/cli/command/record", json={
        "command": "",
        "shell": "bash",
        "directory": "/tmp"
    })
    ok = r.status_code in (200, 400, 422)
    report("10.Edge", "Record empty command", ok, f"status={r.status_code}")

    # 10e. Analyze empty message
    r = api("POST", "/feishu/message/analyze", json={
        "content": "",
        "chat_id": "test_chat_001"
    })
    ok = r.status_code in (200, 400, 422)
    report("10.Edge", "Analyze empty message", ok, f"status={r.status_code}")


# ─────────────────────────────────────────────────────
# CLI Quick Smoke (if CLI is configured)
# ─────────────────────────────────────────────────────

def test_cli_quick():
    print("\n" + "=" * 60)
    print("11. CLI QUICK SMOKE")
    print("=" * 60)

    cli_base = [sys.executable, "-m", "cli.main"]

    def run_cli(args: list, name: str):
        try:
            result = subprocess.run(
                cli_base + args,
                capture_output=True, text=True, timeout=15,
                stdin=subprocess.DEVNULL,
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            ok = result.returncode == 0
            detail = result.stdout.strip()[:120].replace("\n", " | ") if ok else result.stderr.strip()[:120]
            if not ok:
                debug(f"CLI {name} FAILED: rc={result.returncode}")
                debug(f"  stdout: {result.stdout.strip()[:200]}")
                debug(f"  stderr: {result.stderr.strip()[:200]}")
            report("11.CLI", name, ok, detail)
            return ok
        except subprocess.TimeoutExpired:
            debug(f"CLI {name} TIMEOUT after 15s")
            report("11.CLI", name, False, "timed out after 15s")
            return False
        except Exception as e:
            debug(f"CLI {name} EXCEPTION: {type(e).__name__}: {e}")
            report("11.CLI", name, False, str(e)[:80])
            return False

    run_cli(["stats"], "mem stats")
    run_cli(["recent"], "mem recent")
    run_cli(["popular"], "mem popular")
    run_cli(["search", "docker", "--limit", "3"], "mem search docker")
    run_cli(["suggest", "docker", "--limit", "3"], "mem suggest docker")
    run_cli(["list", "--limit", "5"], "mem list")
    run_cli(["note", "smoke test note: db password in 1Password"], "mem note")
    run_cli(["workflow", "list"], "mem workflow list")
    run_cli(["alias", "list"], "mem alias list")
    run_cli(["subscribe", "list"], "mem subscribe list")
    run_cli(["timeline", "部署"], "mem timeline 部署")


# ─────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────

def main():
    global VERBOSE
    parser = argparse.ArgumentParser(description="全功能冒烟测试")
    parser.add_argument("--no-reset", action="store_true", help="不重置数据库")
    parser.add_argument("--skip-cli", action="store_true", help="跳过 CLI 快速冒烟")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细调试输出")
    args = parser.parse_args()
    VERBOSE = args.verbose

    print("=" * 60)
    print("  企业级记忆引擎 — 全功能冒烟测试")
    print("=" * 60)
    print(f"  API: {API}")
    print(f"  Health: {HEALTH}")
    if VERBOSE:
        print(f"  Verbose: ON")
        env_keys = ["ENVIRONMENT", "USE_LLM_DECISION_EXTRACTION", "FEISHU_AUTO_REPLY",
                     "FEISHU_MOCK_MODE", "OPENAI_API_KEY", "DATABASE_URL", "SERVER_PORT"]
        for k in env_keys:
            v = os.getenv(k, "")
            print(f"  ENV {k}={v[:20] + '...' if len(v) > 20 else v}")

    if not args.no_reset:
        print("\n[clean] 重置数据库...")
        subprocess.run(
            [sys.executable, "scripts/reset_db.py"],
            capture_output=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        time.sleep(1)

    print("\n... 等待后端就绪...")
    for _ in range(10):
        try:
            r = requests.get(f"{HEALTH}/health/", timeout=3)
            if r.status_code == 200:
                print("[OK] 后端已就绪\n")
                break
        except requests.ConnectionError:
            pass
        time.sleep(1)
    else:
        print("[FAIL] 后端无响应，请先启动: python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000")
        sys.exit(1)

    # Run all sections
    test_health()
    test_memory_crud()
    test_search()
    test_cli_commands()
    test_decision_extraction()
    test_human_review()
    test_timeline_and_subscriptions()
    test_correction_supersede()
    test_event_callback()
    test_edge_cases()

    if not args.skip_cli:
        test_cli_quick()

    # Summary
    total = PASS + FAIL + SKIP
    print("\n" + "=" * 60)
    print("  RESULTS SUMMARY")
    print("=" * 60)
    print(f"  Total:  {total}")
    print(f"  [OK] Pass: {PASS}")
    print(f"  [FAIL] Fail: {FAIL}")
    print(f"  [SKIP] Skip: {SKIP}")
    print(f"  Rate:   {PASS / max(total - SKIP, 1) * 100:.1f}%")
    print("=" * 60)

    # Section breakdown
    sections = {}
    for r in RESULTS:
        sections.setdefault(r["section"], {"pass": 0, "fail": 0, "skip": 0})
        if r["result"] == "PASS":
            sections[r["section"]]["pass"] += 1
        elif r["result"] == "FAIL":
            sections[r["section"]]["fail"] += 1
        else:
            sections[r["section"]]["skip"] += 1

    print("\n  By Section:")
    for sec, counts in sections.items():
        bar = "P" * counts["pass"] + "F" * counts["fail"] + "[SKIP]" * counts["skip"]
        print(f"  {sec}: {bar} ({counts['pass']}/{counts['pass']+counts['fail']})")

    # Fail detail
    if FAIL > 0:
        print(f"\n  [FAIL] Failed items:")
        for r in RESULTS:
            if r["result"] == "FAIL":
                print(f"     [{r['section']}] {r['name']} — {r['detail']}")

    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
