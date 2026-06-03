"""
AI 社群情报控制台 — Vercel 母舰 Serverless API
接收用户端上传的分类消息，提供管理员查询接口。

存储策略：
- Vercel 部署：内存存储（冷启动重置），生产环境建议迁移到 Vercel Postgres 或 Supabase
- 本地开发：自动持久化到 data/messages.json
"""
import json
import os
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="AI Console Mothership", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ADMIN_KEY = os.environ.get("ADMIN_KEY", "")

# ── Rate Limiting ─────────────────────────────────────────
_rate_store: dict[str, list[float]] = {}
RATE_LIMIT = 60  # 每个 IP 每分钟最大请求数
RATE_WINDOW = 60  # 窗口（秒）


def _check_rate_limit(ip: str):
    """简单的滑动窗口限流。"""
    import time as _t
    now = _t.time()
    if ip not in _rate_store:
        _rate_store[ip] = []
    # 清理过期记录
    _rate_store[ip] = [t for t in _rate_store[ip] if now - t < RATE_WINDOW]
    if len(_rate_store[ip]) >= RATE_LIMIT:
        raise HTTPException(429, "Too many requests")
    _rate_store[ip].append(now)


DATA_DIR = Path(__file__).parent.parent / "data"
DATA_FILE = DATA_DIR / "messages.json"

# ── 存储层 ────────────────────────────────────────────────

_messages: list[dict] = []
_users: dict[str, dict] = {}


def _load_data():
    """从文件加载数据（本地开发用）。"""
    global _messages, _users
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            _messages = data.get("messages", [])
            _users = data.get("users", {})
        except (json.JSONDecodeError, OSError):
            pass


def _save_data():
    """持久化到文件（本地开发用）。Vercel 环境跳过。"""
    if os.environ.get("VERCEL"):
        return
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"messages": _messages, "users": _users}, f, ensure_ascii=False)
    except OSError as e:
        print(f"[WARN] Failed to save data: {e}", flush=True)


# 启动时加载
_load_data()


# ── 数据模型 ──────────────────────────────────────────────

class IngestPayload(BaseModel):
    node_name: str
    uin: str = ""
    nickname: str = ""
    messages: list[dict]


# ── 接口：用户端上传消息 ──────────────────────────────────

@app.post("/api/ingest")
async def ingest(request: Request, payload: IngestPayload):
    """接收用户端上传的分类消息。"""
    _check_rate_limit(request.client.host if request.client else "unknown")
    if not payload.messages:
        raise HTTPException(400, "No messages")

    ts = time.time()
    node = payload.node_name

    if node not in _users:
        _users[node] = {"uin": payload.uin, "nickname": payload.nickname,
                        "first_seen": ts, "msg_count": 0}
    _users[node]["last_seen"] = ts
    if payload.uin:
        _users[node]["uin"] = payload.uin
    if payload.nickname:
        _users[node]["nickname"] = payload.nickname

    # 去重：基于 msg_id
    existing_ids = {m.get("msg_id") for m in _messages}
    accepted = 0
    for msg in payload.messages:
        mid = msg.get("msg_id", "")
        if mid and mid in existing_ids:
            continue
        msg["_node"] = node
        msg["_ingested_at"] = ts
        _messages.append(msg)
        existing_ids.add(mid)
        accepted += 1

    _users[node]["msg_count"] += accepted
    _save_data()
    return {"status": "ok", "accepted": accepted, "total": len(_messages)}


# ── 接口：管理员查询 ──────────────────────────────────────

def _check_admin(request: Request):
    key = request.headers.get("X-Admin-Key", "") or request.query_params.get("admin_key", "")
    if key != ADMIN_KEY:
        raise HTTPException(403, "Invalid admin key")


@app.get("/api/admin/messages")
async def admin_messages(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    node: Optional[str] = None,
    category: Optional[str] = None,
):
    _check_admin(request)
    filtered = _messages
    if node:
        filtered = [m for m in filtered if m.get("_node") == node]
    if category:
        filtered = [m for m in filtered if m.get("category") == category]
    return {
        "total": len(filtered),
        "messages": filtered[offset: offset + limit],
    }


@app.get("/api/admin/users")
async def admin_users(request: Request):
    _check_admin(request)
    return {"users": [
        {"node_name": name, **info}
        for name, info in _users.items()
    ]}


@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    _check_admin(request)
    categories = {}
    nodes = {}
    for m in _messages:
        cat = m.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1
        node = m.get("_node", "unknown")
        nodes[node] = nodes.get(node, 0) + 1
    return {
        "total_messages": len(_messages),
        "total_users": len(_users),
        "categories": categories,
        "nodes": nodes,
    }


@app.get("/api/admin/export")
async def admin_export(request: Request, format: str = Query("json")):
    """导出所有消息数据。"""
    _check_admin(request)
    if format == "jsonl":
        lines = [json.dumps(m, ensure_ascii=False) for m in _messages]
        return JSONResponse(content={"format": "jsonl", "count": len(lines), "data": "\n".join(lines)})
    return JSONResponse(content={"format": "json", "count": len(_messages), "messages": _messages})


# ── 接口：健康检查 ────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "ts": int(time.time()), "messages": len(_messages), "users": len(_users)}


# Vercel 入口
handler = app
