# -*- coding: utf-8 -*-
"""
NapCatQQ 绿色版自动下载与配置脚本
从 GitHub Releases 下载最新 Windows x64 版本（含 Node.js），解压并配置。
"""
import io
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent
NAPCAT_DIR = BASE_DIR / "NapCat_Portable"

# GitHub 代理前缀（国内加速）
PROXY_PREFIXES = [
    "https://ghproxy.net/",
    "https://mirror.ghproxy.com/",
    "https://gh-proxy.com/",
    "",  # 直连作为最后降级
]

GITHUB_API = "https://api.github.com/repos/NapNeko/NapCatQQ/releases/latest"

# NapCat 配置模板
ONEBOT11_CONFIG = {
    "network": {
        "httpServers": [],
        "httpSseServers": [],
        "httpClients": [],
        "websocketServers": [
            {
                "name": "websocket-server",
                "enable": True,
                "host": "0.0.0.0",
                "port": 3001,
                "messagePostFormat": "array",
                "reportSelfMessage": False,
                "token": "",
                "enableForcePushEvent": True,
                "debug": False,
                "heartInterval": 30000,
            }
        ],
        "websocketClients": [],
        "plugins": [],
    },
    "musicSignUrl": "",
    "enableLocalFile2Url": False,
    "parseMultMsg": False,
    "imageDownloadProxy": "",
    "timeout": {
        "baseTimeout": 10000,
        "uploadSpeedKBps": 256,
        "downloadSpeedKBps": 256,
        "maxTimeout": 180000,
    },
}

WEBUI_CONFIG = {
    "host": "::",
    "port": 6099,
    "token": "",  # 运行时由 build 脚本或用户自行设置
    "loginRate": 10,
    "autoLoginAccount": "",
}

NAPCAT_CONFIG = {
    "fileLog": False,
    "consoleLog": True,
    "fileLogLevel": "debug",
    "consoleLogLevel": "info",
    "packetBackend": "auto",
    "packetServer": "",
    "o3HookMode": 1,
    "bypass": {
        "hook": False,
        "window": False,
        "module": False,
        "process": False,
        "container": False,
        "js": False,
    },
}

LAUNCH_BAT_CONTENT = """@echo off
chcp 65001 >nul
title NapCatQQ - Portable
echo ============================================
echo   NapCatQQ Portable Edition
echo ============================================
echo.

:: Set paths
set NAPCAT_DIR=%~dp0
set NODE_EXE=%NAPCAT_DIR%node.exe
set INDEX_JS=%NAPCAT_DIR%index.js

:: Check node.exe
if not exist "%NODE_EXE%" (
    echo [ERROR] node.exe not found in %NAPCAT_DIR%
    echo [ERROR] This NapCat package may be corrupted.
    pause
    exit /b 1
)

:: Check index.js (Shell.Windows.Node entry point)
if exist "%INDEX_JS%" (
    echo [INFO] Starting NapCatQQ (Shell mode)...
    echo [INFO] WebSocket server on port 3001
    echo [INFO] WebUI on port 6099
    echo.
    "%NODE_EXE%" "%INDEX_JS%"
    pause
    exit /b 0
)

:: Fallback: check napcat/napcat.mjs (standalone shell mode)
set NAPCAT_MJS=%NAPCAT_DIR%napcat\\napcat.mjs
if exist "%NAPCAT_MJS%" (
    echo [INFO] Starting NapCatQQ (Legacy shell mode)...
    echo [INFO] WebSocket server on port 3001
    echo [INFO] WebUI on port 6099
    echo.
    "%NODE_EXE%" "%NAPCAT_MJS%"
    pause
    exit /b 0
)

echo [ERROR] No entry point found (index.js or napcat.mjs).
pause
exit /b 1
"""


def fetch_json(url: str, timeout: int = 15) -> dict:
    """Fetch JSON from URL."""
    req = Request(url, headers={"User-Agent": "NapCatFetcher/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download_with_proxy(url: str, timeout: int = 120) -> bytes:
    """Download file, trying multiple proxy prefixes."""
    for proxy in PROXY_PREFIXES:
        full_url = proxy + url if proxy else url
        label = proxy if proxy else "direct"
        try:
            print(f"  Trying {label}...")
            req = Request(full_url, headers={"User-Agent": "NapCatFetcher/1.0"})
            with urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                print(f"  Downloaded {len(data) // 1024 // 1024}MB via {label}")
                return data
        except (URLError, OSError, TimeoutError) as e:
            print(f"  Failed via {label}: {e}")
            continue
    raise RuntimeError("All download attempts failed. Check your network.")


def get_latest_release() -> tuple[str, str]:
    """Get latest release tag and Windows Node zip download URL."""
    print(f"  Querying GitHub API: {GITHUB_API}")
    data = fetch_json(GITHUB_API)
    tag = data["tag_name"]
    print(f"  Latest version: {tag}")

    # Find the Windows Node zip asset
    target_name = "NapCat.Shell.Windows.Node.zip"
    for asset in data.get("assets", []):
        name = asset["name"]
        if name == target_name:
            return tag, asset["browser_download_url"]

    # Fallback: try NapCat.Shell.zip (needs system Node.js)
    print(f"  [WARN] {target_name} not found, falling back to NapCat.Shell.zip")
    for asset in data.get("assets", []):
        if asset["name"] == "NapCat.Shell.zip":
            return tag, asset["browser_download_url"]

    raise RuntimeError("No suitable NapCat release asset found.")


def download_and_extract(download_url: str):
    """Download zip and extract to NapCat_Portable."""
    print(f"\n[Download] {download_url}")
    zip_data = download_with_proxy(download_url)

    # Clean target directory
    if NAPCAT_DIR.exists():
        shutil.rmtree(NAPCAT_DIR)
    NAPCAT_DIR.mkdir(parents=True)

    # Extract
    print(f"\n[Extract] Extracting to {NAPCAT_DIR}...")
    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        # Check if zip has a top-level directory
        names = zf.namelist()
        top_levels = set()
        for n in names:
            parts = n.split("/")
            if len(parts) > 1 and parts[0]:
                top_levels.add(parts[0])

        if len(top_levels) == 1 and not any("/" not in n for n in names):
            # Has a single top-level dir — extract and move contents up
            top_dir = top_levels.pop()
            zf.extractall(BASE_DIR)
            src = BASE_DIR / top_dir
            for item in src.iterdir():
                shutil.move(str(item), str(NAPCAT_DIR / item.name))
            src.rmdir()
            print(f"  Extracted (unwrapped {top_dir}/)")
        else:
            zf.extractall(NAPCAT_DIR)
            print(f"  Extracted directly")

    # Verify key files
    has_node = (NAPCAT_DIR / "node.exe").exists()
    has_index = (NAPCAT_DIR / "index.js").exists()
    has_napcat_mjs = (NAPCAT_DIR / "napcat" / "napcat.mjs").exists()
    print(f"  node.exe: {'OK' if has_node else 'NOT FOUND (will need system Node.js)'}")
    print(f"  index.js: {'OK' if has_index else 'NOT FOUND'}")
    print(f"  napcat/napcat.mjs: {'OK' if has_napcat_mjs else 'NOT FOUND'}")

    return has_node


def generate_configs():
    """Generate NapCat configuration files."""
    config_dir = NAPCAT_DIR / "config"
    config_dir.mkdir(exist_ok=True)

    # onebot11.json — WebSocket server on port 3001
    with open(config_dir / "onebot11.json", "w", encoding="utf-8") as f:
        json.dump(ONEBOT11_CONFIG, f, indent=2, ensure_ascii=False)

    # webui.json — WebUI on port 6099
    with open(config_dir / "webui.json", "w", encoding="utf-8") as f:
        json.dump(WEBUI_CONFIG, f, indent=2, ensure_ascii=False)

    # napcat.json — core config
    with open(config_dir / "napcat.json", "w", encoding="utf-8") as f:
        json.dump(NAPCAT_CONFIG, f, indent=2, ensure_ascii=False)

    print("  Generated onebot11.json (WS port 3001)")
    print("  Generated webui.json (port 6099)")
    print("  Generated napcat.json")


def generate_launch_script():
    """Generate the portable launch batch script."""
    bat_path = NAPCAT_DIR / "napcat.bat"
    bat_path.write_text(LAUNCH_BAT_CONTENT, encoding="utf-8")
    print(f"  Generated napcat.bat")


def main():
    print("=" * 50)
    print("  NapCatQQ Portable Fetcher")
    print("=" * 50)

    if NAPCAT_DIR.exists():
        print(f"\n[Clean] Removing old {NAPCAT_DIR}...")
        shutil.rmtree(NAPCAT_DIR)

    print("\n[Step 1] Checking latest release...")
    tag, download_url = get_latest_release()

    print(f"\n[Step 2] Downloading NapCat {tag}...")
    has_node = download_and_extract(download_url)

    print("\n[Step 3] Generating configuration...")
    generate_configs()
    generate_launch_script()

    # Summary
    total_size = sum(f.stat().st_size for f in NAPCAT_DIR.rglob("*") if f.is_file())
    print(f"\n{'=' * 50}")
    print(f"  NapCat {tag} ready!")
    print(f"  Location: {NAPCAT_DIR}")
    print(f"  Size: {total_size // 1024 // 1024}MB")
    print(f"  Bundled Node.js: {'Yes' if has_node else 'No (needs system Node.js)'}")
    print(f"  WebSocket: ws://127.0.0.1:3001")
    print(f"  WebUI: http://127.0.0.1:6099")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
