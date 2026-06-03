"""
AI 社群情报控制台 — FastAPI 后端
配置管理 · NapCat 登录 · 消息查询 · SSE 实时推送
"""
import asyncio
import base64
import hashlib
import json
import os
import sqlite3
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
import yaml
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── 路径 ──────────────────────────────────────────────────
# APP_DIR: 应用程序文件（EXE、前端、NapCat）— 不动
# DATA_DIR: 用户数据（数据库、配置）— 存到 %APPDATA%，更新不丢失
if os.environ.get("AI_CONSOLE_BASE"):
    APP_DIR = Path(os.environ["AI_CONSOLE_BASE"])
elif getattr(sys, 'frozen', False):
    APP_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).parent

# 用户数据目录：开发模式在 APP_DIR，生产模式在 %APPDATA%/AIConsole
if getattr(sys, 'frozen', False):
    DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "AIConsole"
else:
    DATA_DIR = APP_DIR

DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = DATA_DIR / "config.yaml"
DB_PATH = DATA_DIR / "market.db"

# NapCat 路径：开发模式在上级目录，分发包在同级目录
NAPCAT_DIR = APP_DIR.parent / "NapCat_Portable"
if not NAPCAT_DIR.exists():
    NAPCAT_DIR = APP_DIR / "NapCat_Portable"

# ── SSE 广播队列 ──────────────────────────────────────────
_subscribers: list[asyncio.Queue] = []


def _broadcast(msg: dict):
    for q in _subscribers:
        q.put_nowait(msg)


async def _event_stream():
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.append(q)
    try:
        while True:
            try:
                data = await asyncio.wait_for(q.get(), timeout=15)
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                # keepalive 每 15s 发一次，防止连接断开
                yield ": keepalive\n\n"
    finally:
        _subscribers.remove(q)


# ── 配置读写 ──────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    # 首次运行：从应用目录复制默认配置到数据目录
    default_cfg = APP_DIR / "config.yaml"
    if default_cfg.exists():
        import shutil
        shutil.copy2(str(default_cfg), str(CONFIG_PATH))
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)


# ── 母舰上传 ─────────────────────────────────────────────

async def upload_to_mothership(messages: list[dict], cfg: dict = None):
    """将分类消息上传到 Vercel 母舰。异步执行，不阻塞主流程。"""
    if cfg is None:
        cfg = load_config()
    ms = cfg.get("mothership", {})
    url = ms.get("url", "")
    if not url:
        return
    node_name = ms.get("node_name", "default")
    payload = {
        "node_name": node_name,
        "uin": "",
        "nickname": "",
        "messages": messages,
    }
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
            r = await client.post(f"{url}/api/ingest", json=payload)
            if r.status_code != 200:
                print(f"  [ERR] mothership upload: {r.status_code} {r.text[:100]}", flush=True)
    except Exception as e:
        print(f"  [ERR] mothership upload: {type(e).__name__}: {e}", flush=True)


# ── NapCat WebUI 鉴权 ────────────────────────────────────

def _password_hash(token: str) -> str:
    return hashlib.sha256((token + ".napcat").encode()).hexdigest()


# WebUI credential 缓存
_napcat_cred_cache = {"cred": "", "expires": 0.0}


async def _napcat_login(client: httpx.AsyncClient) -> str:
    """获取 WebUI 凭证，返回 Credential 字符串（带 5 分钟缓存）。"""
    import time
    now = time.time()
    if _napcat_cred_cache["cred"] and now < _napcat_cred_cache["expires"]:
        return _napcat_cred_cache["cred"]

    cfg = load_config()
    webui_url = cfg.get("napcat", {}).get("webui_url", "http://127.0.0.1:6099")
    token = cfg.get("napcat", {}).get("webui_token", "")
    h = _password_hash(token)
    r = await client.post(f"{webui_url}/api/auth/login", json={"hash": h}, timeout=5)
    data = r.json()
    if data.get("code") != 0:
        if _napcat_cred_cache["cred"]:
            return _napcat_cred_cache["cred"]
        raise HTTPException(502, f"NapCat WebUI login failed: {data}")
    cred = data["data"]["Credential"]
    _napcat_cred_cache["cred"] = cred
    _napcat_cred_cache["expires"] = now + 300
    return cred


# ── 数据库 ────────────────────────────────────────────────

def _init_db():
    conn = sqlite3.connect(str(DB_PATH))
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
    # 为旧表添加 chat_type 字段（如果不存在）
    cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
    if "chat_type" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN chat_type TEXT DEFAULT 'group'")
    # 为旧表添加 node_name 字段（用户隔离）
    if "node_name" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN node_name TEXT DEFAULT ''")
    # 批量处理缓冲池
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
    # 全量暗影归档表
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
    # 收藏表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bookmarks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            msg_id      TEXT UNIQUE,
            folder      TEXT DEFAULT '默认收藏',
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 周报缓存表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS summary_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start  TEXT,
            week_end    TEXT,
            category    TEXT,
            summary     TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def _get_current_node_name() -> str:
    """获取当前用户的 node_name。"""
    cfg = load_config()
    return cfg.get("mothership", {}).get("node_name", "") or cfg.get("node_name", "")


def _query_messages(category: Optional[str], limit: int, offset: int,
                    search: Optional[str] = None, days: Optional[int] = None,
                    folder: Optional[str] = None) -> list[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    conditions = []
    params = []

    # 用户隔离：只返回当前用户的消息
    node_name = _get_current_node_name()
    if node_name:
        conditions.append("node_name=?")
        params.append(node_name)

    if category:
        conditions.append("category=?")
        params.append(category)
    if search:
        conditions.append("(summary LIKE ? OR raw_content LIKE ? OR sender_name LIKE ? OR group_name LIKE ?)")
        kw = f"%{search}%"
        params.extend([kw, kw, kw, kw])
    if days:
        conditions.append("created_at >= datetime('now', ?)")
        params.append(f"-{days} days")
    if folder:
        conditions.append("msg_id IN (SELECT msg_id FROM bookmarks WHERE folder=?)")
        params.append(folder)

    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"SELECT * FROM messages{where} ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(sql, params).fetchall()

    # 附加收藏信息
    bookmarks = {r[0] for r in conn.execute("SELECT msg_id FROM bookmarks").fetchall()}
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        d["tags"] = json.loads(d["tags"]) if d["tags"] else []
        d["bookmarked"] = d["msg_id"] in bookmarks
        result.append(d)
    return result


def _query_stats() -> dict:
    conn = sqlite3.connect(str(DB_PATH))
    node_name = _get_current_node_name()
    if node_name:
        where = " WHERE node_name=?"
        p = [node_name]
        total = conn.execute(f"SELECT COUNT(*) FROM messages{where}", p).fetchone()[0]
        a = conn.execute(f"SELECT COUNT(*) FROM messages{where} AND category='A'", p).fetchone()[0]
        b = conn.execute(f"SELECT COUNT(*) FROM messages{where} AND category='B'", p).fetchone()[0]
        c = conn.execute(f"SELECT COUNT(*) FROM messages{where} AND category='C'", p).fetchone()[0]
    else:
        total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        a = conn.execute("SELECT COUNT(*) FROM messages WHERE category='A'").fetchone()[0]
        b = conn.execute("SELECT COUNT(*) FROM messages WHERE category='B'").fetchone()[0]
        c = conn.execute("SELECT COUNT(*) FROM messages WHERE category='C'").fetchone()[0]
    conn.close()
    return {"total": total, "A": a, "B": b, "C": c}


# ── 启动/关闭 ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db()
    yield


# ── FastAPI ───────────────────────────────────────────────

app = FastAPI(title="AI 社群情报控制台", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常捕获 — 防止未处理异常导致进程退出。"""
    import traceback
    tb = traceback.format_exc()
    print(f"[ERR] Unhandled exception on {request.url.path}:\n{tb}", flush=True)
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=500, content={"error": str(exc)})


# ── 数据模型 ──────────────────────────────────────────────

class ConfigPayload(BaseModel):
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model: Optional[str] = None
    napcat_group_ids: Optional[list[int]] = None
    scraper_mode: Optional[str] = None
    mothership_url: Optional[str] = None
    node_name: Optional[str] = None


# ── 接口：健康检查 ────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "ts": int(time.time())}


@app.get("/api/services")
async def services_status():
    """返回各服务的运行状态。"""
    napcat_webui = _is_port_open(6099)
    napcat_ws = _is_port_open(3001)
    cfg = load_config()
    llm_key = cfg.get("llm", {}).get("api_key", "")
    llm_model = cfg.get("llm", {}).get("model", "")
    return {
        "napcat_webui": napcat_webui,
        "napcat_ws": napcat_ws,
        "api_server": True,
        "ws_config_ok": napcat_ws,
        "llm_configured": bool(llm_key),
        "llm_model": llm_model or "未配置",
    }


# ── 接口：配置管理 ────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    cfg = load_config()
    llm = cfg.get("llm", {})
    key = llm.get("api_key", "")
    masked = ("*" * max(0, len(key) - 4)) + key[-4:] if len(key) > 4 else key
    return {
        "llm_api_key": masked,
        "llm_base_url": llm.get("base_url", ""),
        "llm_model": llm.get("model", ""),
        "configured": bool(key),
        "scraper_mode": cfg.get("scraper", {}).get("mode", "realtime"),
        "mothership_url": cfg.get("mothership", {}).get("url", ""),
        "node_name": cfg.get("mothership", {}).get("node_name", ""),
    }


@app.post("/api/config")
async def post_config(payload: ConfigPayload):
    cfg = load_config()
    if "llm" not in cfg:
        cfg["llm"] = {}
    if payload.llm_api_key is not None:
        cfg["llm"]["api_key"] = payload.llm_api_key
    if payload.llm_base_url is not None:
        cfg["llm"]["base_url"] = payload.llm_base_url
    if payload.llm_model is not None:
        cfg["llm"]["model"] = payload.llm_model
    if payload.napcat_group_ids is not None:
        if "napcat" not in cfg:
            cfg["napcat"] = {}
        cfg["napcat"]["group_ids"] = payload.napcat_group_ids
    if payload.scraper_mode is not None:
        if payload.scraper_mode not in ("realtime", "batch"):
            raise HTTPException(400, "scraper_mode must be 'realtime' or 'batch'")
        if "scraper" not in cfg:
            cfg["scraper"] = {}
        cfg["scraper"]["mode"] = payload.scraper_mode
    if payload.mothership_url is not None:
        if "mothership" not in cfg:
            cfg["mothership"] = {}
        cfg["mothership"]["url"] = payload.mothership_url
    if payload.node_name is not None:
        if "mothership" not in cfg:
            cfg["mothership"] = {}
        cfg["mothership"]["node_name"] = payload.node_name
    save_config(cfg)
    return {"status": "saved"}


# ── 接口：用户注册/身份 ──────────────────────────────────

class RegisterPayload(BaseModel):
    nickname: str


@app.post("/api/register")
async def register_user(payload: RegisterPayload):
    """用户注册：设置昵称，用于数据隔离。"""
    nickname = payload.nickname.strip()
    if not nickname or len(nickname) > 20:
        raise HTTPException(400, "昵称需要 1-20 个字符")
    cfg = load_config()
    if "mothership" not in cfg:
        cfg["mothership"] = {}
    cfg["mothership"]["node_name"] = nickname
    # 也存一份到顶层，方便读取
    cfg["node_name"] = nickname
    save_config(cfg)
    return {"status": "ok", "node_name": nickname}


@app.get("/api/user")
async def get_user():
    """获取当前用户信息。"""
    cfg = load_config()
    node_name = cfg.get("mothership", {}).get("node_name", "") or cfg.get("node_name", "")
    return {"node_name": node_name, "registered": bool(node_name)}


@app.get("/api/user/stats")
async def get_user_stats():
    """获取当前用户的统计数据。"""
    conn = sqlite3.connect(str(DB_PATH))
    node_name = _get_current_node_name()
    if node_name:
        where = " WHERE node_name=?"
        p = [node_name]
        today_count = conn.execute(f"SELECT COUNT(*) FROM messages{where} AND DATE(created_at)=DATE('now')", p).fetchone()[0]
        total_count = conn.execute(f"SELECT COUNT(*) FROM messages{where}", p).fetchone()[0]
        bookmark_count = conn.execute(f"SELECT COUNT(*) FROM bookmarks").fetchone()[0]
    else:
        today_count = conn.execute("SELECT COUNT(*) FROM messages WHERE DATE(created_at)=DATE('now')").fetchone()[0]
        total_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        bookmark_count = conn.execute("SELECT COUNT(*) FROM bookmarks").fetchone()[0]
    conn.close()
    return {"today": today_count, "total": total_count, "bookmarks": bookmark_count}


# ── 接口：NapCat 登录 ────────────────────────────────────

@app.get("/api/login/qrcode")
async def get_qrcode():
    cfg = load_config()
    webui_url = cfg.get("napcat", {}).get("webui_url", "http://127.0.0.1:6099")
    platform = cfg.get("napcat", {}).get("login_platform", "iPad")
    # 优先：通过 NapCat WebUI API 获取（POST 方法）
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            cred = await _napcat_login(client)
            headers = {"Authorization": f"Bearer {cred}"}
            # 先设置平台
            try:
                await client.post(f"{webui_url}/api/QQLogin/SetPlatform", headers=headers, json={"platform": platform}, timeout=3)
            except Exception:
                pass  # 如果 NapCat 不支持此接口，忽略
            r = await client.post(f"{webui_url}/api/QQLogin/GetQQLoginQrcode", headers=headers, timeout=5)
            data = r.json()
            if data.get("code") == 0 and data.get("data"):
                qr_data = data["data"]
                # NapCat v4 返回 {"qrcode": "https://..."} 格式
                qr_url = qr_data.get("qrcode", "") if isinstance(qr_data, dict) else ""
                if qr_url:
                    # 用 qrcode 库生成 base64 PNG
                    try:
                        import qrcode, io, base64
                        img = qrcode.make(qr_url)
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        b64 = base64.b64encode(buf.getvalue()).decode()
                        return {"status": "ok", "qrcode": b64, "format": "png"}
                    except ImportError:
                        return {"status": "ok", "qrcode": qr_url, "format": "url"}
    except Exception:
        pass
    # 降级：读取本地缓存
    qr_paths = [
        NAPCAT_DIR / "napcat" / "cache" / "qrcode.png",
        NAPCAT_DIR / "NapCat" / "cache" / "qrcode.png",
    ]
    for qr_path in qr_paths:
        if qr_path.exists() and qr_path.stat().st_size > 100:
            b64 = base64.b64encode(qr_path.read_bytes()).decode()
            return {"status": "ok", "qrcode": b64, "format": "png"}
    # 最终降级：返回占位 SVG
    return {"status": "mock", "qrcode": _mock_qr_svg(), "format": "svg"}


@app.get("/api/qrcode")
async def get_qrcode_image():
    """直接返回 QR 码 PNG 二进制流，供前端 <img src> 直接引用。"""
    import io
    # 1) 通过 NapCat WebUI API 获取 QR URL，再生成 PNG
    try:
        cfg = load_config()
        webui_url = cfg.get("napcat", {}).get("webui_url", "http://127.0.0.1:6099")
        platform = cfg.get("napcat", {}).get("login_platform", "iPad")
        async with httpx.AsyncClient(trust_env=False) as client:
            cred = await _napcat_login(client)
            headers = {"Authorization": f"Bearer {cred}"}
            # 先设置平台
            try:
                await client.post(f"{webui_url}/api/QQLogin/SetPlatform", headers=headers, json={"platform": platform}, timeout=3)
            except Exception:
                pass
            r = await client.post(f"{webui_url}/api/QQLogin/GetQQLoginQrcode", headers=headers, timeout=5)
            data = r.json()
            if data.get("code") == 0 and data.get("data"):
                qr_url = data["data"].get("qrcode", "") if isinstance(data["data"], dict) else ""
                if qr_url:
                    try:
                        import qrcode
                        img = qrcode.make(qr_url)
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        from fastapi.responses import Response
                        return Response(content=buf.getvalue(), media_type="image/png")
                    except ImportError:
                        pass
    except Exception:
        pass

    # 2) 降级：读取磁盘缓存
    qr_paths = [
        NAPCAT_DIR / "napcat" / "cache" / "qrcode.png",
        NAPCAT_DIR / "NapCat" / "cache" / "qrcode.png",
    ]
    for qr_path in qr_paths:
        if qr_path.exists() and qr_path.stat().st_size > 100:
            from fastapi.responses import Response
            return Response(content=qr_path.read_bytes(), media_type="image/png")
    raise HTTPException(404, "QR code not ready")


def _hide_args() -> dict:
    """返回 subprocess 隐藏窗口的参数（与 launcher.py 保持一致）。"""
    import subprocess
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return {
        "startupinfo": si,
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }


def _restart_napcat_sync():
    """静默重启 NapCat — 杀掉 NapCat 进程后在后台重新启动，不弹窗。"""
    import subprocess
    import time as _time

    # 1) 只杀 NapCat 相关的 node 进程（通过 cmdline 包含 napcat 判断）
    napcat_killed = False
    try:
        import psutil
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = (p.info["name"] or "").lower()
                cmdline = " ".join(p.info["cmdline"] or []).lower()
                if name == "node.exe" and "napcat" in cmdline:
                    p.kill()
                    napcat_killed = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except ImportError:
        # psutil 不可用时用 wmic 精确查找 napcat 进程
        try:
            result = subprocess.run(
                ['wmic', 'process', 'where', "name='node.exe' and commandline like '%napcat%'", 'get', 'processid'],
                capture_output=True, text=True, timeout=10,
                **_hide_args(),
            )
            for line in result.stdout.strip().split('\n'):
                line = line.strip()
                if line.isdigit():
                    subprocess.run(['taskkill', '/F', '/PID', line], capture_output=True, timeout=5, **_hide_args())
                    napcat_killed = True
        except Exception:
            pass
    except Exception:
        pass

    if not napcat_killed:
        return

    _time.sleep(3)

    # 2) 静默启动 NapCat（使用 STARTUPINFO 隐藏窗口，与 launcher.py 一致）
    napcat_dir = NAPCAT_DIR
    node_exe = napcat_dir / "node.exe"
    if not node_exe.exists():
        node_exe = "node.exe"  # fallback to PATH

    entry = None
    if (napcat_dir / "index.js").exists():
        entry = "index.js"
    elif (napcat_dir / "napcat" / "napcat.mjs").exists():
        entry = "napcat\\napcat.mjs"
    if entry:
        subprocess.Popen(
            [str(node_exe), entry],
            cwd=str(napcat_dir),
            **_hide_args(),
        )


@app.post("/api/login/password")
async def login_with_password(request: Request):
    """使用 QQ 账号密码登录（通过 NapCat WebUI API）。
    请求体: {"uin": "QQ号", "password": "明文密码"}
    NapCat API 接收的是 passwordMd5（MD5 哈希）。"""
    body = await request.json()
    uin = str(body.get("uin", "")).strip()
    password = str(body.get("password", "")).strip()
    if not uin or not password:
        raise HTTPException(400, "请填写 QQ 号和密码")

    # 计算 MD5 哈希
    password_md5 = hashlib.md5(password.encode()).hexdigest()

    cfg = load_config()
    webui_url = cfg.get("napcat", {}).get("webui_url", "http://127.0.0.1:6099")

    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            # 1) 先登录 WebUI 获取 Credential
            cred = await _napcat_login(client)
            headers = {"Authorization": f"Bearer {cred}"}

            # 2) 调用 NapCat 密码登录 API（带平台参数）
            cfg = load_config()
            platform = cfg.get("napcat", {}).get("login_platform", "iPad")
            r = await client.post(
                f"{webui_url}/api/QQLogin/PasswordLogin",
                headers=headers,
                json={"uin": uin, "passwordMd5": password_md5, "platform": platform},
                timeout=10,
            )
            data = r.json()
            print(f"[LOGIN-DEBUG] PasswordLogin response: {json.dumps(data, ensure_ascii=False)[:500]}", flush=True)

            code = data.get("code", -1)
            msg = data.get("msg", "") or data.get("message", "")

            # code == 0 表示成功
            if code == 0:
                return {"status": "ok", "message": "登录请求已发送，请等待验证完成"}

            # 需要验证码的情况
            if "captcha" in msg.lower() or "verify" in msg.lower() or code == 100:
                return {
                    "status": "need_captcha",
                    "message": "需要验证码，请使用扫码登录或完成人机验证后重试",
                    "detail": msg,
                }

            # 其他错误
            return {"status": "error", "message": msg or f"登录失败 (code={code})"}

    except httpx.ConnectError:
        raise HTTPException(502, "无法连接到 NapCat WebUI，请确认 NapCat 已启动")
    except Exception as e:
        print(f"[LOGIN-ERROR] Password login failed: {type(e).__name__}: {e}", flush=True)
        raise HTTPException(500, f"登录失败: {e}")


@app.post("/api/login/reset")
async def login_reset():
    """清除 NapCat 登录锁和 QQ 登录缓存，强制重新扫码。"""
    import shutil
    cleaned = []

    # 1) 清除 QQ 登录 token（解决"已登录,无法重复登录"问题）
    login_enc = Path(os.environ.get("APPDATA", "")) / "QQ" / "auth" / "login.enc"
    if login_enc.exists():
        login_enc.unlink()
        cleaned.append(str(login_enc))

    # 2) 清除 QQNT session 数据
    qq_partitions = Path(os.environ.get("APPDATA", "")) / "QQ" / "Partitions"
    if qq_partitions.exists():
        for session_dir in qq_partitions.iterdir():
            if session_dir.name.startswith("qqnt_"):
                for subdir in ["Session Storage", "Local Storage", "Cache", "Code Cache", "Network", "IndexedDB"]:
                    target = session_dir / subdir
                    if target.exists():
                        shutil.rmtree(target, ignore_errors=True)
                        cleaned.append(str(target))

    # 3) 清除 NapCat 账号专属配置（让 NapCat 重新生成）
    napcat_cfg_dir = NAPCAT_DIR / "napcat" / "config"
    if napcat_cfg_dir.exists():
        for f in napcat_cfg_dir.glob("onebot11_*.json"):
            f.unlink()
            cleaned.append(str(f))
        for f in napcat_cfg_dir.glob("napcat_protocol_*.json"):
            f.unlink()
            cleaned.append(str(f))

    # 4) 清除 QR 缓存
    qr_paths = [
        NAPCAT_DIR / "napcat" / "cache" / "qrcode.png",
        NAPCAT_DIR / "NapCat" / "cache" / "qrcode.png",
    ]
    for p in qr_paths:
        if p.exists():
            p.unlink()
            cleaned.append(str(p))

    # 5) 重启 NapCat（线程池执行，不阻塞事件循环）
    import asyncio as _aio
    loop = _aio.get_event_loop()
    loop.run_in_executor(None, _restart_napcat_sync)

    return {"status": "ok", "cleaned": cleaned, "message": "登录缓存已清除，NapCat 已重启，请重新扫码"}


class PlatformPayload(BaseModel):
    platform: str  # "Windows", "iPad", "Android"


@app.post("/api/login/platform")
async def set_login_platform(payload: PlatformPayload):
    """设置登录平台（Windows/iPad/Android）。
    iPad 和 Android 协议可与电脑端 QQ 同时在线。"""
    platform = payload.platform
    if platform not in ("Windows", "iPad", "Android"):
        raise HTTPException(400, "platform 必须是 Windows、iPad 或 Android")

    cfg = load_config()
    if "napcat" not in cfg:
        cfg["napcat"] = {}
    cfg["napcat"]["login_platform"] = platform
    save_config(cfg)
    return {"status": "ok", "platform": platform}


@app.get("/api/login/platform")
async def get_login_platform():
    """获取当前登录平台设置。"""
    cfg = load_config()
    platform = cfg.get("napcat", {}).get("login_platform", "iPad")
    return {"platform": platform}


WS_SERVER_CONFIG = [
    {
        "name": "websocket-server",
        "enable": True,
        "host": "0.0.0.0",
        "port": 3001,
        "messagePostFormat": "array",
        "reportSelfMessage": True,
        "token": "",
        "enableForcePushEvent": True,
        "debug": False,
        "heartInterval": 30000,
    }
]


def _ensure_ws_config(uin: str) -> bool:
    """检查并修复 NapCat 账号专属配置，确保 WebSocket 服务器已启用。
    同时修复 onebot11_{uin}.json 和 napcat_protocol_{uin}.json。
    返回 True 表示配置被修改（需要重启 NapCat）。"""
    napcat_config_dir = NAPCAT_DIR / "napcat" / "config"
    modified = False

    # 修复 napcat_protocol_{uin}.json（这个文件会覆盖 onebot11 配置）
    protocol_cfg = napcat_config_dir / f"napcat_protocol_{uin}.json"
    try:
        if protocol_cfg.exists():
            with open(protocol_cfg, "r", encoding="utf-8") as f:
                pdata = json.load(f)
        else:
            pdata = {}
    except (json.JSONDecodeError, OSError):
        pdata = {}

    if not pdata.get("network", {}).get("websocketServers"):
        pdata["enable"] = True
        if "network" not in pdata:
            pdata["network"] = {}
        pdata["network"]["websocketServers"] = WS_SERVER_CONFIG
        with open(protocol_cfg, "w", encoding="utf-8") as f:
            json.dump(pdata, f, indent=2, ensure_ascii=False)
        modified = True

    # 修复 onebot11_{uin}.json
    account_cfg = napcat_config_dir / f"onebot11_{uin}.json"
    if account_cfg.exists():
        try:
            with open(account_cfg, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}

        if not data.get("network", {}).get("websocketServers"):
            if "network" not in data:
                data["network"] = {}
            data["network"]["websocketServers"] = WS_SERVER_CONFIG
            with open(account_cfg, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            modified = True

    return modified


def _is_port_open(port: int) -> bool:
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        return result == 0
    except Exception:
        return False


_last_napcat_restart = 0.0  # 上次自动重启 NapCat 的时间戳


def _log_login_debug(msg: str):
    """写调试日志到文件（方便排查，不依赖控制台）。"""
    try:
        log_path = BASE_DIR / "login_debug.log"
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass
    print(msg, flush=True)


def _detect_login_by_ws_raw() -> dict | None:
    """用原始 socket 连接 WebSocket 服务器检测登录状态（无外部依赖）。
    NapCat 登录后，WS 连接建立时会立即推送 meta_event，包含 self_id。"""
    ws_port = 3001
    if not _is_port_open(ws_port):
        _log_login_debug("[WS-RAW] Port 3001 not open, skipping")
        return None

    try:
        import socket
        import struct
        import random

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(("127.0.0.1", ws_port))

        # WebSocket 握手
        key_bytes = bytes([random.randint(0, 255) for _ in range(16)])
        import base64 as _b64
        ws_key = _b64.b64encode(key_bytes).decode()

        handshake = (
            f"GET / HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{ws_port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {ws_key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        sock.sendall(handshake.encode())

        # 读取握手响应
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk

        if b"101" not in response:
            _log_login_debug(f"[WS-RAW] Handshake failed: {response[:200]}")
            sock.close()
            return None

        _log_login_debug("[WS-RAW] Handshake OK, waiting for data...")

        # 读取 WebSocket 帧（等待最多 5 秒）
        sock.settimeout(5)
        try:
            frame_data = sock.recv(65536)
        except socket.timeout:
            _log_login_debug("[WS-RAW] No data received within 5s")
            sock.close()
            return None

        if len(frame_data) < 2:
            _log_login_debug("[WS-RAW] Frame too short")
            sock.close()
            return None

        # 解析 WebSocket 帧
        opcode = frame_data[0] & 0x0F
        masked = bool(frame_data[1] & 0x80)
        payload_len = frame_data[1] & 0x7F
        offset = 2

        if payload_len == 126:
            payload_len = struct.unpack(">H", frame_data[2:4])[0]
            offset = 4
        elif payload_len == 127:
            payload_len = struct.unpack(">Q", frame_data[2:10])[0]
            offset = 10

        if masked:
            mask_key = frame_data[offset:offset + 4]
            offset += 4
            payload = bytearray(frame_data[offset:offset + payload_len])
            for i in range(len(payload)):
                payload[i] ^= mask_key[i % 4]
            payload = bytes(payload)
        else:
            payload = frame_data[offset:offset + payload_len]

        if opcode == 1:  # TEXT frame
            text = payload.decode("utf-8", errors="replace")
            _log_login_debug(f"[WS-RAW] Received: {text[:500]}")
            try:
                data = json.loads(text)
                if data.get("post_type") == "meta_event":
                    self_id = str(data.get("self_id", ""))
                    if self_id and self_id != "0":
                        sock.close()
                        return {"status": "logged_in", "uin": self_id, "nickname": ""}
            except json.JSONDecodeError:
                pass

        sock.close()
    except Exception as e:
        _log_login_debug(f"[WS-RAW] Error: {type(e).__name__}: {e}")

    return None


def _detect_login_by_config_files() -> dict | None:
    """通过 NapCat 配置文件 + WS 端口验证检测已登录的 QQ 账号。
    配置文件在登出后也会存在，所以必须同时验证 WS 服务器（端口 3001）是否在运行。
    WS 端口打开 = NapCat 已登录且正在推送消息。"""
    napcat_config_dir = NAPCAT_DIR / "napcat" / "config"
    if not napcat_config_dir.exists():
        return None

    # 配置文件只是用来获取 UIN，真正的登录确认要看 WS 端口
    if not _is_port_open(3001):
        _log_login_debug("[FILE-DETECT] Config files exist but WS port 3001 not open → not logged in")
        return None

    for f in napcat_config_dir.glob("onebot11_*.json"):
        uin = f.stem.replace("onebot11_", "")
        if uin and uin != "0":
            nickname = ""
            napcat_cfg = napcat_config_dir / f"napcat_{uin}.json"
            if napcat_cfg.exists():
                try:
                    with open(napcat_cfg, "r", encoding="utf-8") as fh:
                        nc = json.load(fh)
                    nickname = nc.get("nickname", "")
                except Exception:
                    pass
            _log_login_debug(f"[FILE-DETECT] Config + WS port OK for UIN: {uin}")
            return {"status": "logged_in", "uin": uin, "nickname": nickname}
    return None


@app.get("/api/login/status")
async def get_login_status():
    cfg = load_config()
    webui_url = cfg.get("napcat", {}).get("webui_url", "http://127.0.0.1:6099")
    _log_login_debug("[LOGIN] === Status check started ===")

    # 1) 尝试通过 WebUI API 获取登录信息
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            cred = await _napcat_login(client)
            headers = {"Authorization": f"Bearer {cred}"}

            # 尝试 GetQQLoginInfo
            try:
                r = await client.post(f"{webui_url}/api/QQLogin/GetQQLoginInfo", headers=headers, timeout=5)
                data = r.json()
                _log_login_debug(f"[LOGIN] GetQQLoginInfo: code={data.get('code')} data={json.dumps(data.get('data'), ensure_ascii=False)[:500]}")

                if data.get("code") == 0 and data.get("data"):
                    info = data["data"]
                    uin = str(info.get("uin", ""))
                    nickname = info.get("nick", "") or info.get("nickname", "") or info.get("nickName", "")

                    # 多种方式判断在线状态
                    online = False
                    if info.get("online") is True:
                        online = True
                    status_val = str(info.get("status", "")).lower()
                    if status_val in ("online", "1", "true"):
                        online = True
                    login_state = info.get("loginState", info.get("login_state", ""))
                    if str(login_state).lower() in ("1", "true", "online", "loggedin"):
                        online = True
                    if info.get("isLoggedIn") is True:
                        online = True
                    # 有有效 uin 就认为已登录
                    if not online and uin and uin != "0":
                        online = True

                    _log_login_debug(f"[LOGIN] uin={uin} nick={nickname} online={online}")

                    if uin and uin != "0" and online:
                        ws_ok = _is_port_open(3001)
                        ws_config_fixed = False
                        if not ws_ok:
                            _ensure_ws_config(uin)
                            # 冷却机制：60 秒内只重启一次，防止循环重启
                            global _last_napcat_restart
                            now = time.time()
                            if now - _last_napcat_restart > 60:
                                _last_napcat_restart = now
                                _log_login_debug(f"[LOGIN] WS port 3001 not open, auto-restarting NapCat...")
                                import asyncio as _aio
                                loop = _aio.get_event_loop()
                                loop.run_in_executor(None, _restart_napcat_sync)
                            else:
                                _log_login_debug(f"[LOGIN] WS port 3001 not open, restart cooldown active")
                            ws_config_fixed = True
                        return {"status": "logged_in", "uin": uin, "nickname": nickname, "ws_config_fixed": ws_config_fixed}
            except Exception as e:
                _log_login_debug(f"[LOGIN] GetQQLoginInfo failed: {type(e).__name__}: {e}")

            # 备用：GetLoginList
            try:
                r2 = await client.post(f"{webui_url}/api/QQLogin/GetLoginList", headers=headers, timeout=5)
                data2 = r2.json()
                _log_login_debug(f"[LOGIN] GetLoginList: {json.dumps(data2, ensure_ascii=False)[:500]}")
                if data2.get("code") == 0 and data2.get("data"):
                    login_list = data2["data"]
                    items = login_list if isinstance(login_list, list) else [login_list]
                    for account in items:
                        acc_uin = str(account.get("uin", ""))
                        if acc_uin and acc_uin != "0":
                            nickname = account.get("nick", "") or account.get("nickname", "")
                            return {"status": "logged_in", "uin": acc_uin, "nickname": nickname, "ws_config_fixed": False}
            except Exception as e:
                _log_login_debug(f"[LOGIN] GetLoginList failed: {type(e).__name__}: {e}")

    except Exception as e:
        _log_login_debug(f"[LOGIN] WebUI auth failed: {type(e).__name__}: {e}")

    # 2) 降级：原始 WebSocket 连接检测（无外部依赖）
    ws_result = _detect_login_by_ws_raw()
    if ws_result:
        return ws_result

    # 3) 降级：通过 NapCat 配置文件检测（最终兜底）
    file_result = _detect_login_by_config_files()
    if file_result:
        return file_result

    # 4) 检测 NapCat 是否正在运行
    if _is_port_open(6099):
        return {"status": "waiting_scan"}

    return {"status": "offline"}


@app.post("/api/restart-napcat")
async def restart_napcat():
    """静默重启 NapCat 进程（不弹窗）。"""
    import asyncio as _aio
    loop = _aio.get_event_loop()
    loop.run_in_executor(None, _restart_napcat_sync)
    return {"status": "restarted", "message": "NapCat 正在重启，请稍后重新扫码登录"}


# ── 接口：消息查询 ────────────────────────────────────────

@app.get("/api/messages")
async def get_messages(
    category: Optional[str] = Query(None, pattern="^[ABC]$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    days: Optional[int] = Query(None, ge=1, le=365),
    folder: Optional[str] = Query(None),
):
    return _query_messages(category, limit, offset, search=search, days=days, folder=folder)


@app.post("/api/mothership/sync")
async def mothership_sync():
    """手动触发：将本地未上传的消息批量推送到母舰。"""
    cfg = load_config()
    ms = cfg.get("mothership", {})
    url = ms.get("url", "")
    if not url:
        raise HTTPException(400, "母舰地址未配置")

    rows = _query_messages(limit=200)
    if not rows:
        return {"status": "no_data", "uploaded": 0}

    await upload_to_mothership(rows, cfg)
    return {"status": "ok", "uploaded": len(rows)}


@app.get("/api/mothership/test")
async def mothership_test():
    """测试母舰连通性。"""
    cfg = load_config()
    ms = cfg.get("mothership", {})
    url = ms.get("url", "")
    if not url:
        return {"connected": False, "error": "母舰地址未配置"}
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            r = await client.get(f"{url}/api/health")
            if r.status_code == 200:
                return {"connected": True, "remote": r.json()}
            return {"connected": False, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"connected": False, "error": str(e)}


# ── 接口：统计 ────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats():
    return _query_stats()


# ── 接口：删除消息 ────────────────────────────────────────

@app.delete("/api/messages/{msg_id}")
async def delete_message(msg_id: str):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("DELETE FROM messages WHERE id=? OR msg_id=?", (msg_id, msg_id))
    conn.execute("DELETE FROM bookmarks WHERE msg_id=?", (msg_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted"}


class BatchDeletePayload(BaseModel):
    ids: list[int]


@app.post("/api/messages/delete_batch")
async def delete_batch(payload: BatchDeletePayload):
    if not payload.ids:
        return {"status": "ok", "deleted": 0}
    conn = sqlite3.connect(str(DB_PATH))
    placeholders = ",".join("?" * len(payload.ids))
    # 先删除关联的收藏
    conn.execute(f"DELETE FROM bookmarks WHERE msg_id IN (SELECT msg_id FROM messages WHERE id IN ({placeholders}))", payload.ids)
    # 再删除消息
    cur = conn.execute(f"DELETE FROM messages WHERE id IN ({placeholders})", payload.ids)
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return {"status": "ok", "deleted": deleted}


# ── 接口：收藏 ────────────────────────────────────────────

class BookmarkPayload(BaseModel):
    msg_id: str
    folder: str = "默认收藏"


@app.post("/api/bookmarks")
async def add_bookmark(payload: BookmarkPayload):
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            "INSERT OR REPLACE INTO bookmarks (msg_id, folder) VALUES (?, ?)",
            (payload.msg_id, payload.folder),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "bookmarked"}


@app.delete("/api/bookmarks/{msg_id}")
async def remove_bookmark(msg_id: str):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("DELETE FROM bookmarks WHERE msg_id=?", (msg_id,))
    conn.commit()
    conn.close()
    return {"status": "unbookmarked"}


@app.get("/api/bookmarks")
async def list_bookmarks(folder: Optional[str] = Query(None)):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    if folder:
        rows = conn.execute("SELECT * FROM bookmarks WHERE folder=? ORDER BY id DESC", (folder,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM bookmarks ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 接口：收藏夹管理 ──────────────────────────────────────

@app.get("/api/folders")
async def list_folders():
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute("SELECT folder, COUNT(*) as count FROM bookmarks GROUP BY folder ORDER BY folder").fetchall()
    conn.close()
    return [{"name": r[0], "count": r[1]} for r in rows]


class FolderRenamePayload(BaseModel):
    old_name: str
    new_name: str


@app.post("/api/folders/rename")
async def rename_folder(payload: FolderRenamePayload):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("UPDATE bookmarks SET folder=? WHERE folder=?", (payload.new_name, payload.old_name))
    conn.commit()
    conn.close()
    return {"status": "renamed"}


@app.delete("/api/folders/{name}")
async def delete_folder(name: str):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("DELETE FROM bookmarks WHERE folder=?", (name,))
    conn.commit()
    conn.close()
    return {"status": "folder_deleted"}


# ── 接口：周报 ────────────────────────────────────────────

@app.get("/api/weekly_summaries")
async def list_weekly_summaries():
    """返回所有已缓存的历史周报列表。"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT week_start, week_end, category, summary, created_at FROM summary_log ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/weekly_summary")
async def weekly_summary(category: Optional[str] = Query(None, pattern="^[ABC]$")):
    import datetime as _dt
    today = _dt.date.today()
    week_start = today - _dt.timedelta(days=today.weekday())
    week_end = week_start + _dt.timedelta(days=6)
    ws, we = week_start.isoformat(), week_end.isoformat()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # 检查缓存
    cached = conn.execute(
        "SELECT summary FROM summary_log WHERE week_start=? AND category=? ORDER BY id DESC LIMIT 1",
        (ws, category or "ALL"),
    ).fetchone()
    if cached:
        conn.close()
        return {"week_start": ws, "week_end": we, "category": category, "summary": cached["summary"], "cached": True}

    # 查询本周消息
    conditions = ["created_at >= ?", "created_at <= ?"]
    params: list = [ws + " 00:00:00", we + " 23:59:59"]
    if category:
        conditions.append("category=?")
        params.append(category)
    where = " WHERE " + " AND ".join(conditions)
    rows = conn.execute(f"SELECT category, summary, tags, sender_name, group_name, created_at FROM messages{where} ORDER BY created_at", params).fetchall()
    conn.close()

    if not rows:
        return {"week_start": ws, "week_end": we, "category": category, "summary": "本周暂无消息。", "cached": False}

    # 拼 prompt
    lines = []
    for r in rows:
        tags = json.loads(r["tags"]) if r["tags"] else []
        lines.append(f"[{r['category']}] {r['created_at']} {r['group_name']}/{r['sender_name']}: {r['summary']} {' '.join('#'+t for t in tags)}")

    cfg = load_config()
    llm = cfg.get("llm", {})
    api_key = llm.get("api_key", "")
    base_url = llm.get("base_url", "https://api.deepseek.com/v1")
    model = llm.get("model", "deepseek-chat")

    if not api_key:
        return {"week_start": ws, "week_end": we, "category": category, "summary": "未配置 LLM API Key，无法生成周报。", "cached": False}

    prompt = f"""以下是本周（{ws} ~ {we}）的社群情报消息，共 {len(lines)} 条。
请按以下格式生成周报摘要：

1. **A 类（重要信息）**：本周有哪些重要事项？列出关键点。
2. **B 类（校园轶事）**：本周有哪些有趣的校园故事？
3. **C 类（二手资讯）**：本周有哪些二手交易信息？

如果某个类别没有消息，简短说明即可。使用简洁的中文。

消息列表：
{chr(10).join(lines[:200])}"""

    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 1500, "temperature": 0.3},
                timeout=60,
            )
            data = resp.json()
            summary = data["choices"][0]["message"]["content"]
    except Exception as e:
        summary = f"周报生成失败：{e}"

    # 缓存
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "INSERT INTO summary_log (week_start, week_end, category, summary) VALUES (?, ?, ?, ?)",
        (ws, we, category or "ALL", summary),
    )
    conn.commit()
    conn.close()

    return {"week_start": ws, "week_end": we, "category": category, "summary": summary, "cached": False}


# ── 接口：SSE 实时推送 ────────────────────────────────────

@app.get("/api/stream")
async def stream():
    return StreamingResponse(_event_stream(), media_type="text/event-stream")


# ── 接口：供 scraper 写入已分类消息 ────────────────────────

class ClassifiedMessage(BaseModel):
    msg_id: str
    chat_type: str = "group"
    group_id: str = ""
    group_name: str = ""
    sender_id: str
    sender_name: str
    raw_content: str
    category: str
    summary: str
    tags: list[str]
    created_at: str = ""


@app.post("/api/ingest")
async def ingest(msg: ClassifiedMessage):
    ts = msg.created_at or time.strftime("%Y-%m-%d %H:%M:%S")
    node_name = _get_current_node_name()
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            """INSERT OR IGNORE INTO messages
               (msg_id, chat_type, group_id, group_name, sender_id, sender_name, raw_content, category, summary, tags, created_at, node_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (msg.msg_id, msg.chat_type, msg.group_id, msg.group_name,
             msg.sender_id, msg.sender_name, msg.raw_content,
             msg.category, msg.summary, json.dumps(msg.tags, ensure_ascii=False), ts, node_name),
        )
        conn.commit()
    finally:
        conn.close()
    _broadcast({
        "type": "new_message",
        "data": {
            "msg_id": msg.msg_id,
            "chat_type": msg.chat_type,
            "group_id": msg.group_id,
            "group_name": msg.group_name,
            "sender_id": msg.sender_id,
            "sender_name": msg.sender_name,
            "raw_content": msg.raw_content,
            "category": msg.category,
            "summary": msg.summary,
            "tags": msg.tags,
            "created_at": ts,
        },
    })
    return {"status": "ok"}


# ── 接口：缓冲池（batch 模式） ───────────────────────────

class BufferMessage(BaseModel):
    msg_id: str
    chat_type: str = "group"
    chat_id: str = ""
    chat_name: str = ""
    sender_id: str
    sender_name: str
    raw_content: str
    created_at: str = ""


@app.post("/api/buffer")
async def buffer_message(msg: BufferMessage):
    ts = msg.created_at or time.strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            """INSERT OR IGNORE INTO raw_buffer
               (msg_id, chat_type, chat_id, chat_name, sender_id, sender_name, raw_content, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (msg.msg_id, msg.chat_type, msg.chat_id, msg.chat_name,
             msg.sender_id, msg.sender_name, msg.raw_content, ts),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "buffered"}


@app.get("/api/buffer_stats")
async def buffer_stats():
    conn = sqlite3.connect(str(DB_PATH))
    total = conn.execute("SELECT COUNT(*) FROM raw_buffer").fetchone()[0]
    conn.close()
    return {"buffered": total}


# ── 接口：全量暗影归档 ───────────────────────────────────

class ArchiveMessage(BaseModel):
    msg_id: str
    chat_type: str = "group"
    chat_name: str = ""
    sender_name: str
    raw_content: str
    created_at: str = ""


@app.post("/api/archive_ingest")
async def archive_ingest(msg: ArchiveMessage):
    ts = msg.created_at or time.strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            """INSERT OR IGNORE INTO raw_archive
               (msg_id, chat_type, chat_name, sender_name, raw_content, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (msg.msg_id, msg.chat_type, msg.chat_name,
             msg.sender_name, msg.raw_content, ts),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "archived"}


@app.get("/api/archive_stats")
async def archive_stats():
    conn = sqlite3.connect(str(DB_PATH))
    total = conn.execute("SELECT COUNT(*) FROM raw_archive").fetchone()[0]
    conn.close()
    return {"archived": total}


@app.get("/api/archive")
async def get_archive(request: Request):
    cfg = load_config()
    admin_key = cfg.get("admin_key", "")
    provided = request.headers.get("X-Admin-Key", "")
    if not admin_key or provided != admin_key:
        raise HTTPException(403, "ACCESS DENIED")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM raw_archive ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


BATCH_PROMPT = """你是一个语义话题聚类引擎。以下是一段群聊/私聊的完整对话记录。

你的任务：阅读所有消息，按【讨论的语义话题】进行聚类，识别出独立的讨论线程。

═══ 最高原则：按语义聚类，严禁按发言人聚类 ═══

错误示例：把 User A 的所有消息归为一个话题 — 这是完全错误的！
正确示例：User A 提问 → User B 回答 → User C 反驳 → User A 追问，这四条消息属于同一个话题。
判断依据：「这些消息是否在讨论同一件事」，而不是「这些消息是否来自同一个人」。

═══ 强制规则 ═══

1. 按【语义话题】聚类，绝对不按【发言人】聚类。
   - 同一话题可以包含多个不同用户的发言。
   - 同一用户的不同发言可以分属不同话题。
2. 多人对话必须完整保留：提问、回答、补充、追问、确认、反驳 — 只要围绕同一话题，全部归入同一个 Topic。
3. 每条消息只能归属于一个话题。
4. 如果所有消息都是废话，返回空数组 []。

═══ 高召回率约束 ═══

- 每个话题的 original_messages 必须 100% 包含所有相关原始消息，一条不准遗漏。
- content 字段必须是原始消息的逐字拷贝，严禁篡改、缩写、改写。
- original_messages 必须按时间顺序排列。
- 宁可多收录，不可遗漏。

═══ A 类：重要信息（绝对白名单，极度严格）═══

仅且只有以下内容归为 A：
- 学校/学院/老师/教务处发布的官方通知、公告
- 考试安排、课程调整、放假通知
- 作业/论文/项目的截止日期（DDL）
- 奖学金、评优、保研等官方政策变动
- 紧急安全事项、突发事件通知

🔥 A 类铁律 — 以下内容严禁归为 A：
- 政治讨论、历史争论、社会热点辩论（如阶级斗争、地主、战争讨论）→ 必须归为 B
- 学术争论、课程内容讨论 → 必须归为 B
- 个人观点、意见表达、情绪吐槽 → 必须归为 B
- 非官方来源的任何信息 → 不得归为 A
- 只有「学校官方」发出的「正式通知」才能是 A，学生之间的讨论永远不是 A

═══ B 类：校园轶事 ═══

- 校园趣闻、吐槽、日常分享、情感表达、段子
- 政治/历史/社会话题的讨论和争论
- 学术讨论、课程内容辩论、学习心得
- 课程评价、社团活动
- 任何形式的观点表达和辩论
- 网络梗、玩梗、meme 讨论

═══ C 类：二手资讯（含虚拟服务）═══

实体物品交易（必须是真实的交易意图）：
- 买卖、转让、求购、拼单、代购、闲置交易

虚拟服务交易：
- 代课、代跑、跑腿、代取快递
- 带饭、帮取外卖
- 拼车、拼房、合租
- 技能交换、有偿帮忙

⚠️ 极度重要 — 识别中文修辞手法，防止误判：
- "砸锅卖铁也要买" 是成语/夸张修辞，意思是"无论如何都要"，绝对不是真的卖废铁！严禁判为 C！
- "卖肾买iPhone" 是网络梗，不是真实的器官交易！严禁判为 C！
- "穷得叮当响" 是夸张，不是在卖东西！
- 判断是否为 C 类的唯一标准：是否存在真实的、具体的交易意图（有人要买/卖某个具体的东西或服务）
- 仅字面提及"卖""买""出"等词汇，但上下文是吐槽、玩梗、夸张修辞的，一律不是 C

═══ None 类：垃圾信息（毫不留情，宁缺毋滥）═══

以下内容必须归为 None，不得生成 Topic：
- 纯表情回复、单字回复（嗯、哦、好、6、啊、哈、草、牛）
- 纯 meme/段子转发（无实质信息）
- emoji 堆砌、无意义的表情包
- 阴阳怪气的讽刺、纯玩梗（无实质内容）
- 无意义的吐槽、情绪宣泄（无信息增量）
- 灌水、刷屏、复读机
- "哈哈哈哈哈"、"笑死"、"绝了" 等纯情绪表达
- 任何不含实质性信息交流的废话

原则：宁可漏掉一条有价值的消息，也绝对不把垃圾信息归入 ABC。如果一条消息删掉后不影响任何人的信息获取，它就是 None。

═══ 输出格式 ═══

严格返回 JSON 数组，不要返回其他内容：
[
  {
    "topic_title": "具体话题标题",
    "category": "A/B/C",
    "summary": "该话题的 1-2 句话总结",
    "tags": ["标签1", "标签2"],
    "original_messages": [
      {"time": "消息时间", "sender": "发送人", "content": "原始消息逐字内容"},
      ...
    ]
  },
  ...
]"""


@app.post("/api/batch_process")
async def batch_process():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM raw_buffer ORDER BY chat_id, created_at").fetchall()
    if not rows:
        conn.close()
        return {"status": "empty", "processed": 0}

    # 按 chat_id 分组
    groups: dict[str, list] = {}
    for r in rows:
        cid = r["chat_id"] or "unknown"
        groups.setdefault(cid, []).append(dict(r))

    cfg = load_config()
    llm_cfg = cfg.get("llm", {})
    api_key = llm_cfg.get("api_key", "")
    base_url = llm_cfg.get("base_url", "https://api.openai.com/v1")
    if not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"
    model = llm_cfg.get("model", "gpt-4o-mini")

    _log_login_debug(f"[BATCH] Processing {len(rows)} messages in {len(groups)} groups, LLM={'on' if api_key else 'off'}")

    all_topics = []
    for cid, msgs in groups.items():
        chat_type = msgs[0]["chat_type"]
        chat_name = msgs[0]["chat_name"]

        # 拼上下文文本给 LLM
        lines = []
        for m in msgs:
            prefix = "群聊" if m["chat_type"] == "group" else "私聊"
            lines.append(f"[{prefix}: {m['chat_name']}] {m['created_at']} | {m['sender_name']}: {m['raw_content']}")
        context_text = "\n".join(lines)

        if not api_key:
            # 降级：规则引擎逐条分类，按类别聚合话题
            from scraper import _rule_classify
            buckets: dict[str, list] = {"A": [], "B": [], "C": []}
            for m in msgs:
                r = _rule_classify(m["raw_content"])
                c = r["category"]
                if c in buckets:
                    buckets[c].append(m)
            for cat, cat_msgs in buckets.items():
                if not cat_msgs:
                    continue
                orig = [{"time": m["created_at"] or "", "sender": m["sender_name"] or "", "content": m["raw_content"] or ""} for m in cat_msgs]
                all_topics.append({
                    "topic_title": f"【批量】{chat_name} — {cat}类话题",
                    "category": cat,
                    "summary": f"共 {len(cat_msgs)} 条相关消息。",
                    "tags": ["规则聚合"],
                    "chat_type": chat_type,
                    "chat_name": chat_name,
                    "original_messages": orig,
                })
            continue

        try:
            async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(connect=5, read=30, write=5, pool=5)) as client:
                r = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": BATCH_PROMPT},
                            {"role": "user", "content": context_text},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 4000,
                    },
                )
                if r.status_code != 200:
                    print(f"  [BATCH LLM HTTP {r.status_code}] {r.text[:200]}", flush=True)
                    continue
                data = r.json()
                text = data["choices"][0]["message"]["content"].strip()
                if "```" in text:
                    text = text.split("```")[1]
                    if text.startswith("json"):
                        text = text[4:]
                    text = text.strip()
                topics = json.loads(text)
                if isinstance(topics, dict):
                    topics = [topics]
                for t in topics:
                    t["chat_type"] = chat_type
                    t["chat_name"] = chat_name
                all_topics.extend(topics)
        except Exception as e:
            print(f"  [BATCH LLM ERROR] {type(e).__name__}: {e}", flush=True)

    # 写入 messages 表 — 每个语义话题独立一张卡片
    inserted = 0
    node_name = _get_current_node_name()
    for topic in all_topics:
        cat = topic.get("category", "None")
        if cat == "None":
            continue
        summary = topic.get("summary", "")
        tags = topic.get("tags", [])
        topic_title = topic.get("topic_title", "话题")
        chat_type = topic.get("chat_type", "group")
        chat_name = topic.get("chat_name", "")
        orig_msgs = topic.get("original_messages", [])

        fake_msg_id = f"batch_{int(time.time())}_{inserted}"
        # raw_content 存 JSON：标题 + 该话题专属的原始消息
        raw_payload = json.dumps({
            "title": topic_title,
            "messages": orig_msgs,
        }, ensure_ascii=False)

        conn.execute(
            """INSERT OR IGNORE INTO messages
               (msg_id, chat_type, group_id, group_name, sender_id, sender_name, raw_content, category, summary, tags, node_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fake_msg_id, chat_type, "", chat_name, "", "",
             f"[批量] {raw_payload}",
             cat, summary, json.dumps(tags, ensure_ascii=False), node_name),
        )
        inserted += 1
        _broadcast({
            "type": "new_message",
            "data": {
                "msg_id": fake_msg_id,
                "chat_type": chat_type,
                "group_id": "",
                "group_name": chat_name,
                "sender_id": "",
                "sender_name": "",
                "raw_content": f"[批量] {topic_title}",
                "category": cat,
                "summary": summary,
                "tags": tags,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
        })

    # 清空 buffer
    conn.execute("DELETE FROM raw_buffer")
    conn.commit()
    conn.close()

    # 上传到母舰
    if all_topics:
        cfg = load_config()
        ms_msgs = []
        for t in all_topics:
            if t.get("category") == "None":
                continue
            ms_msgs.append({
                "msg_id": f"batch_{int(time.time())}_{len(ms_msgs)}",
                "chat_type": t.get("chat_type", "group"),
                "chat_name": t.get("chat_name", ""),
                "sender_name": "",
                "raw_content": t.get("topic_title", ""),
                "category": t.get("category", ""),
                "summary": t.get("summary", ""),
                "tags": t.get("tags", []),
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
        if ms_msgs:
            asyncio.create_task(upload_to_mothership(ms_msgs, cfg))

    return {"status": "ok", "processed": len(rows), "topics": inserted}


# ── 前端静态文件托管（必须在所有 API 路由之后）────────────

DIST_DIR = APP_DIR.parent / "frontend" / "dist"
if not DIST_DIR.exists():
    DIST_DIR = APP_DIR / "dist"

if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(DIST_DIR / "assets")), name="static-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """SPA 兜底：非 API 路由全部返回 index.html。"""
        file_path = DIST_DIR / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(DIST_DIR / "index.html"))


# ── 工具 ──────────────────────────────────────────────────

def _mock_qr_svg() -> str:
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="260" height="260" viewBox="0 0 260 260">'
    svg += '<rect width="260" height="260" fill="#111"/>'
    svg += '<text x="130" y="125" text-anchor="middle" font-family="monospace" font-size="13" fill="#555">NapCat</text>'
    svg += '<text x="130" y="145" text-anchor="middle" font-family="monospace" font-size="13" fill="#555">未检测到</text>'
    svg += '</svg>'
    return base64.b64encode(svg.encode()).decode()


# ── 启动 ──────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    import logging
    from logging.handlers import RotatingFileHandler
    # 写错误日志到文件，自动轮转（单文件 5MB，保留 3 个备份）
    log_file = BASE_DIR / "api.log"
    file_handler = RotatingFileHandler(
        str(log_file), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            file_handler,
        ],
    )
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
