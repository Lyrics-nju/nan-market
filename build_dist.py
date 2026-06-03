# -*- coding: utf-8 -*-
"""
AI 社群情报控制台 — 多节点自动化打包脚本
自动完成前端构建、基础包生成、多节点分发。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import yaml

BASE_DIR = Path(__file__).parent
FRONTEND_DIR = BASE_DIR / "frontend"
BACKEND_DIR = BASE_DIR / "backend"
DIST_DIR = FRONTEND_DIR / "dist"
NAPCAT_DIR = BASE_DIR / "NapCat_Portable"
OUTPUT_DIR = BASE_DIR / "dist_output_v2"

NODE_NAMES = {
    "AI_Console_Node_One": "one",
    "AI_Console_Node_Two": "two",
    "AI_Console_Node_Three": "three",
    "AI_Console_Node_Four": "four",
    "AI_Console_Node_Five": "five",
}

BAT_CONTENT = r"""@echo off
chcp 65001 >nul
title AI 社群情报控制台
echo ============================================
echo   AI 社群情报控制台 - 一键启动
echo ============================================
echo.

:: Use bundled Python (no system dependency required)
set PYTHON=%~dp0python\python.exe
if not exist "%PYTHON%" (
    echo [ERROR] 内嵌 Python 未找到，请重新解压安装包
    pause
    exit /b 1
)
echo [INFO] Python: bundled 3.11

:: Start NapCat (portable, bundled Node.js) — 后台运行，关闭窗口不会终止
if exist "NapCat_Portable" (
    echo [INFO] Starting NapCatQQ engine...
    start "" /b cmd /c "cd /d "%~dp0NapCat_Portable" && node.exe index.js"
    echo [INFO] Waiting 5s for NapCat to initialize...
    timeout /t 5 /nobreak >nul
    echo [INFO] NapCatQQ started (WebUI: http://127.0.0.1:6099)
) else (
    echo [WARN] NapCat_Portable not found, QQ login will not be available
)
echo.

:: Start API server in separate window
echo [INFO] Starting API server (port 8000)...
start "API_Server" cmd /k "cd /d "%~dp0" && "%PYTHON%" api.py"
timeout /t 2 /nobreak >nul

:: Start Scraper in separate window
echo [INFO] Starting Scraper Agent...
start "Scraper_Agent" cmd /k "cd /d "%~dp0" && "%PYTHON%" scraper.py"
timeout /t 1 /nobreak >nul

:: Open browser
echo [INFO] Opening browser...
start http://localhost:8000

echo.
echo ============================================
echo   All services started!
echo   - NapCat:  WS 3001 / WebUI 6099
echo   - API:     http://localhost:8000
echo   - Scraper: watching messages
echo ============================================
echo.
echo   To stop all: close this window, then API_Server and Scraper_Agent windows.
echo.
pause
"""


def run(cmd, cwd=None):
    """Execute command and check return code."""
    print(f"  > {' '.join(cmd)}")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True,
        shell=True, encoding="utf-8", errors="replace", env=env
    )
    if result.returncode != 0:
        print(f"  [STDOUT] {result.stdout[-500:]}")
        print(f"  [STDERR] {result.stderr[-500:]}")
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    return result


def fetch_napcat():
    """Step 0: Download NapCat portable edition."""
    print("\n[Step 0] Fetching NapCatQQ portable...")
    if NAPCAT_DIR.exists():
        print(f"  {NAPCAT_DIR} already exists, skipping download")
        return

    fetch_script = BASE_DIR / "fetch_napcat.py"
    if not fetch_script.exists():
        raise FileNotFoundError(f"fetch_napcat.py not found at {fetch_script}")

    run([sys.executable, str(fetch_script)], cwd=BASE_DIR)

    if not NAPCAT_DIR.exists():
        raise RuntimeError("NapCat download failed — NapCat_Portable not created")
    print("  NapCat fetched OK")


PYTHON_EMBED_URL = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
CACHE_DIR = BASE_DIR / "_cache"
PYTHON_EMBED_DIR = BASE_DIR / "python_embed"


def fetch_python_embed():
    """Download and set up Python embeddable with pip + dependencies."""
    import zipfile
    import urllib.request

    print("\n[Step 0.5] Setting up Python embeddable...")
    CACHE_DIR.mkdir(exist_ok=True)

    zip_path = CACHE_DIR / "python-3.11.9-embed-amd64.zip"
    if not zip_path.exists():
        print(f"  Downloading Python 3.11.9 embeddable...")
        urllib.request.urlretrieve(PYTHON_EMBED_URL, str(zip_path))
        print(f"  Downloaded: {zip_path.stat().st_size // 1024 // 1024}MB")
    else:
        print(f"  Using cached: {zip_path}")

    # Extract
    if PYTHON_EMBED_DIR.exists():
        shutil.rmtree(PYTHON_EMBED_DIR)
    PYTHON_EMBED_DIR.mkdir()

    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(PYTHON_EMBED_DIR)
    print("  Extracted Python embeddable")

    # Fix python311._pth — uncomment "import site"
    pth_files = list(PYTHON_EMBED_DIR.glob("python*._pth"))
    for pth in pth_files:
        content = pth.read_text(encoding="utf-8")
        content = content.replace("#import site", "import site")
        pth.write_text(content, encoding="utf-8")
        print(f"  Fixed {pth.name}: enabled import site")

    # Download get-pip.py
    get_pip_path = CACHE_DIR / "get-pip.py"
    if not get_pip_path.exists():
        print("  Downloading get-pip.py...")
        urllib.request.urlretrieve(GET_PIP_URL, str(get_pip_path))

    # Install pip
    print("  Installing pip...")
    py_exe = str(PYTHON_EMBED_DIR / "python.exe")
    result = subprocess.run(
        [py_exe, str(get_pip_path), "--no-warn-script-location"],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        print(f"  [WARN] get-pip stderr: {result.stderr[-200:]}")
    print("  pip installed")

    # Install dependencies
    req_path = BACKEND_DIR / "requirements.txt"
    print(f"  Installing dependencies from {req_path.name}...")
    result = subprocess.run(
        [py_exe, "-m", "pip", "install", "-r", str(req_path),
         "-q", "--no-warn-script-location"],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        print(f"  [WARN] pip install stderr: {result.stderr[-300:]}")
    print("  Dependencies installed")

    size = sum(f.stat().st_size for f in PYTHON_EMBED_DIR.rglob("*") if f.is_file())
    print(f"  Python embed ready: {size // 1024 // 1024}MB")
    return PYTHON_EMBED_DIR


def build_frontend():
    """Step 1: Build frontend."""
    print("\n[Step 1] Building frontend...")
    if not FRONTEND_DIR.exists():
        raise FileNotFoundError(f"Frontend dir not found: {FRONTEND_DIR}")

    if not (FRONTEND_DIR / "node_modules").exists():
        print("  Installing frontend dependencies...")
        run(["npm", "install"], cwd=FRONTEND_DIR)

    run(["npm", "run", "build"], cwd=FRONTEND_DIR)

    if not DIST_DIR.exists():
        raise FileNotFoundError(f"Build failed, dist not found: {DIST_DIR}")
    print("  Frontend build OK")


def create_base_package():
    """Step 2: Create base package folder."""
    print("\n[Step 2] Creating base package AI_Console_Base...")
    base = OUTPUT_DIR / "AI_Console_Base"

    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)

    # Copy backend files
    for fname in ["api.py", "scraper.py", "requirements.txt"]:
        src = BACKEND_DIR / fname
        if src.exists():
            shutil.copy2(src, base / fname)
            print(f"  Copied {fname}")

    # Copy config.yaml — 清空敏感信息，用户在网页端自行填写
    cfg_src = BACKEND_DIR / "config.yaml"
    if cfg_src.exists():
        with open(cfg_src, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        if "scraper" not in cfg:
            cfg["scraper"] = {}
        cfg["scraper"]["mode"] = "realtime"
        if "napcat" in cfg:
            cfg["napcat"]["group_ids"] = []
        # 清空 LLM API Key（用户自行填写）
        if "llm" in cfg:
            cfg["llm"]["api_key"] = ""
        # 清空飞书 webhook（保留结构）
        if "feishu_sync" in cfg:
            cfg["feishu_sync"]["enable"] = False
            cfg["feishu_sync"]["webhook_url"] = ""
        # 初始化母舰配置（用户自行填写）
        if "mothership" not in cfg:
            cfg["mothership"] = {"url": "", "node_name": ""}
        # 自动生成随机 token（替换示例值）
        import secrets
        cfg["admin_key"] = secrets.token_urlsafe(16)
        if "napcat" in cfg:
            cfg["napcat"]["webui_token"] = secrets.token_hex(6)
        with open(base / "config.yaml", "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
        print("  Copied config.yaml (sensitive data cleared, tokens auto-generated, mode=realtime)")

    # Create empty SQLite database with all 3 tables
    import sqlite3
    db_path = base / "market.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            msg_id      TEXT UNIQUE,
            chat_type   TEXT DEFAULT 'group',
            group_id    TEXT,
            group_name  TEXT,
            sender_id   TEXT,
            sender_name TEXT,
            raw_content TEXT,
            category    TEXT,
            summary     TEXT,
            tags        TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_buffer (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            msg_id      TEXT UNIQUE,
            chat_type   TEXT,
            chat_id     TEXT,
            chat_name   TEXT,
            sender_id   TEXT,
            sender_name TEXT,
            raw_content TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_archive (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            msg_id      TEXT UNIQUE,
            chat_type   TEXT,
            chat_name   TEXT,
            sender_name TEXT,
            raw_content TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    print("  Created empty SQLite DB (3 tables)")

    # Copy frontend dist
    shutil.copytree(DIST_DIR, base / "dist")
    print("  Copied frontend dist")

    # Copy NapCat portable
    if NAPCAT_DIR.exists():
        shutil.copytree(NAPCAT_DIR, base / "NapCat_Portable")
        napcat_size = sum(f.stat().st_size for f in (base / "NapCat_Portable").rglob("*") if f.is_file())
        print(f"  Copied NapCat_Portable ({napcat_size // 1024 // 1024}MB)")
    else:
        print("  [WARN] NapCat_Portable not found, skipping")

    # Copy bundled Python embeddable
    if PYTHON_EMBED_DIR.exists():
        shutil.copytree(PYTHON_EMBED_DIR, base / "python")
        py_size = sum(f.stat().st_size for f in (base / "python").rglob("*") if f.is_file())
        print(f"  Copied python/ ({py_size // 1024 // 1024}MB)")
    else:
        print("  [WARN] python_embed not found, skipping")

    # Generate launch script
    bat_path = base / "launch.bat"
    bat_path.write_text(BAT_CONTENT, encoding="utf-8-sig")
    print("  Generated launch.bat")

    return base


def create_node_packages(base):
    """Step 3: Copy base package to 3 independent nodes."""
    print("\n[Step 3] Generating multi-node packages...")

    for folder_name, node_name in NODE_NAMES.items():
        node_dir = OUTPUT_DIR / folder_name

        if node_dir.exists():
            shutil.rmtree(node_dir)

        shutil.copytree(base, node_dir)
        print(f"  Created {folder_name}")

        # Modify config.yaml node_name
        cfg_path = node_dir / "config.yaml"
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        if "feishu_sync" not in cfg:
            cfg["feishu_sync"] = {}
        cfg["feishu_sync"]["node_name"] = node_name

        if "mothership" not in cfg:
            cfg["mothership"] = {}
        cfg["mothership"]["node_name"] = node_name

        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)

        print(f"    node_name -> \"{node_name}\"")

    print(f"\n  Generated {len(NODE_NAMES)} node packages")


def create_zips():
    """Step 4: Create ZIP archives for distribution."""
    print("\n[Step 4] Creating ZIP archives...")
    for folder_name in NODE_NAMES:
        folder = OUTPUT_DIR / folder_name
        zip_path = OUTPUT_DIR / f"{folder_name}.zip"
        shutil.make_archive(str(zip_path.with_suffix("")), "zip", OUTPUT_DIR, folder_name)
        size_mb = zip_path.stat().st_size // 1024 // 1024
        print(f"  {folder_name}.zip ({size_mb}MB)")
    print("  ZIP archives created")


def cleanup_folders():
    """Step 5: Clean up unpacked folders, keep only ZIPs and base."""
    print("\n[Step 5] Cleaning up unpacked node folders...")
    for folder_name in NODE_NAMES:
        folder = OUTPUT_DIR / folder_name
        if folder.exists():
            shutil.rmtree(folder)
            print(f"  Removed {folder_name}")

    # Also remove base folder
    base = OUTPUT_DIR / "AI_Console_Base"
    if base.exists():
        shutil.rmtree(base)
        print("  Removed AI_Console_Base")

    # Clean up python embed build dir (keep cache for rebuilds)
    if PYTHON_EMBED_DIR.exists():
        shutil.rmtree(PYTHON_EMBED_DIR)
        print("  Removed python_embed")


def main():
    print("=" * 50)
    print("  AI Console - Multi-Node Build Script")
    print("=" * 50)

    if OUTPUT_DIR.exists():
        try:
            shutil.rmtree(OUTPUT_DIR)
        except PermissionError:
            # Windows 文件锁问题，重命名后删除
            import tempfile
            tmp = Path(tempfile.mkdtemp())
            shutil.move(str(OUTPUT_DIR), str(tmp / "old"))
            shutil.rmtree(tmp)
    OUTPUT_DIR.mkdir(parents=True)

    fetch_napcat()
    fetch_python_embed()
    build_frontend()
    base = create_base_package()
    create_node_packages(base)
    create_zips()
    cleanup_folders()

    print("\n" + "=" * 50)
    print("  Build complete!")
    print(f"  Output: {OUTPUT_DIR.resolve()}")
    print()
    for folder_name in NODE_NAMES:
        print(f"  {folder_name}.zip")
    print()
    print("  Each package contains:")
    print("  +-- api.py")
    print("  +-- scraper.py")
    print("  +-- config.yaml")
    print("  +-- market.db")
    print("  +-- requirements.txt")
    print("  +-- dist/ (frontend static files)")
    print("  +-- NapCat_Portable/ (QQ bot engine)")
    print("  +-- python/ (bundled Python 3.11 + dependencies)")
    print("  +-- launch.bat (one-click start)")
    print()
    print("  Zero dependencies — no Python/Node.js install needed.")
    print("  Just double-click launch.bat.")
    print("=" * 50)


if __name__ == "__main__":
    main()
