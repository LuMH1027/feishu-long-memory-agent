#!/usr/bin/env python3
"""环境自检脚本 —— Python版本、依赖包、.env配置、数据库状态、Embedding服务可达性"""

import importlib.metadata
import os
import sys
from pathlib import Path

# 强制 UTF-8 输出，兼容 Windows GBK 终端
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WORKSPACE = Path(__file__).resolve().parents[1]

REQUIRED_PACKAGES = [
    "fastapi", "uvicorn", "sqlalchemy", "chromadb", "openai",
    "langchain", "typer", "pyperclip", "pydantic", "python-dotenv",
    "pytest", "python-multipart", "requests", "numpy", "pandas",
]

OPTIONAL_PACKAGES = ["lark-oapi"]

REQUIRED_ENV_VARS = [
    "OPENAI_API_KEY", "OPENAI_BASE_URL",
]
OPTIONAL_ENV_VARS = [
    "FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_VERIFICATION_TOKEN", "FEISHU_ENCRYPT_KEY",
]


def _ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def _warn(msg: str) -> None:
    print(f"  ⚠️  {msg}")


def _fail(msg: str) -> None:
    print(f"  ❌ {msg}")


def check_python() -> bool:
    print("🔍 Python 版本")
    v = sys.version_info
    if v >= (3, 10):
        _ok(f"{v.major}.{v.minor}.{v.micro}")
        return True
    _fail(f"{v.major}.{v.minor}.{v.micro} (需要 ≥ 3.10)")
    return False


def check_deps() -> bool:
    print("🔍 依赖包")
    all_ok = True
    for pkg in REQUIRED_PACKAGES:
        try:
            ver = importlib.metadata.version(pkg)
            _ok(f"{pkg}=={ver}")
        except importlib.metadata.PackageNotFoundError:
            _fail(f"{pkg} 未安装")
            all_ok = False
    for pkg in OPTIONAL_PACKAGES:
        try:
            ver = importlib.metadata.version(pkg)
            _ok(f"{pkg}=={ver}")
        except importlib.metadata.PackageNotFoundError:
            _warn(f"{pkg} 未安装 (可选，飞书功能需要)")
    return all_ok


def check_env() -> bool:
    print("🔍 .env 配置")
    env_path = WORKSPACE / ".env"
    if not env_path.exists():
        _fail(".env 文件不存在")
        return False
    _ok(".env 文件存在")

    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except ImportError:
        # 手动解析 .env 文件
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ[key.strip()] = val.strip()

    all_ok = True
    for var in REQUIRED_ENV_VARS:
        val = os.getenv(var)
        if val and val not in ("your_openai_api_key", "your_value", ""):
            _ok(f"{var} = ...{val[-8:]}")
        else:
            _fail(f"{var} 未设置或为占位值")
            all_ok = False

    for var in OPTIONAL_ENV_VARS:
        val = os.getenv(var)
        if val and val not in ("your_feishu_app_id", "your_feishu_app_secret",
                                "your_verification_token", "your_encrypt_key", ""):
            _ok(f"{var} = ...{val[-8:]}")
        else:
            _warn(f"{var} 未设置 (飞书 SDK 将不可用)")

    return all_ok


def check_database() -> bool:
    print("🔍 数据库状态")
    db_url = os.getenv("DATABASE_URL", "sqlite:///./db/memory.db")
    _ok(f"DATABASE_URL = {db_url}")

    if "sqlite" in db_url:
        db_rel = db_url.replace("sqlite:///", "")
        db_path = WORKSPACE / db_rel
        if db_path.exists():
            _ok(f"关系型数据库存在 ({db_path})")
            try:
                from sqlalchemy import create_engine, inspect
                engine = create_engine(db_url, connect_args={"check_same_thread": False})
                inspector = inspect(engine)
                tables = inspector.get_table_names()
                _ok(f"表: {', '.join(tables) if tables else '(空 — 首次运行)'}")
                engine.dispose()
            except Exception as e:
                _fail(f"数据库连接失败: {e}")
                return False
        else:
            _warn("关系型数据库文件不存在 (首次运行会自动创建)")
    else:
        try:
            from sqlalchemy import create_engine, inspect
            engine = create_engine(db_url)
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            _ok(f"远程数据库可达, 表: {', '.join(tables) if tables else '(空)'}")
            engine.dispose()
        except Exception as e:
            _fail(f"远程数据库连接失败: {e}")
            return False

    vector_path = os.getenv("VECTOR_DB_PATH", "./db/vector_store")
    v_path = WORKSPACE / vector_path
    if v_path.exists():
        _ok(f"向量库目录存在 ({v_path})")
        try:
            from db.vector.client import vector_client
            count = vector_client.collection.count()
            _ok(f"向量库集合: {vector_client.collection.name}, 向量数: {count}")
        except Exception as e:
            _fail(f"向量库连接失败: {e}")
            return False
    else:
        _warn("向量库目录不存在 (首次运行会自动创建)")

    return True


def check_embedding() -> bool:
    print("🔍 Embedding 服务可达性")
    try:
        from core.utils.embedding import get_embedding
        embedding = get_embedding("preflight_check")
        dimension = len(embedding)
        model = os.getenv("EMBEDDING_MODEL", "text-embedding-ada-002")
        _ok(f"模型={model}, 维度={dimension}")
        return True
    except Exception as e:
        _fail(f"不可达: {e}")
        return False


def main() -> int:
    print("=" * 50)
    print("  企业级记忆引擎 - 环境自检")
    print("=" * 50)
    print()

    results = {
        "Python": check_python(),
        "依赖包": check_deps(),
        "配置": check_env(),
        "数据库": check_database(),
        "Embedding": check_embedding(),
    }

    print()
    print("=" * 50)
    print("  自检结果")
    print("=" * 50)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    for name, ok in results.items():
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name}")

    print(f"\n  {passed}/{total} 项通过")
    if passed == total:
        print("  🎉 环境就绪，可以启动 Demo")
        return 0
    else:
        print("  ⚠️  存在未通过项，请修复后重试")
        return 1


if __name__ == "__main__":
    sys.exit(main())
