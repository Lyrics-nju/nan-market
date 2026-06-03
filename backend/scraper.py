"""
AI 社群情报控制台 — Scraper Agent
监听 NapCat OneBot11 WebSocket，对群聊消息调用 LLM 三分类。
分类结果写入本地 SQLite（通过 api.py /api/ingest）。
"""
import asyncio
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
import httpx
import yaml

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

if os.environ.get("AI_CONSOLE_BASE"):
    APP_DIR = Path(os.environ["AI_CONSOLE_BASE"])
elif getattr(sys, 'frozen', False):
    APP_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).parent

# 用户数据目录：生产模式在 %APPDATA%/AIConsole
if getattr(sys, 'frozen', False):
    DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "AIConsole"
else:
    DATA_DIR = APP_DIR

DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = DATA_DIR / "config.yaml"
API_BASE = "http://127.0.0.1:8000"

# ── CQ 码清理 ─────────────────────────────────────────────

CQ_PATTERN = re.compile(r'\[CQ:[^\]]+\]')

def strip_cq(raw: str) -> str:
    """移除 CQ 码，只保留纯文本。"""
    return CQ_PATTERN.sub('', raw).strip()

def is_only_cq(raw: str) -> bool:
    """判断消息是否只包含 CQ 码（图片、表情等）。"""
    text = strip_cq(raw)
    return len(text) < 2

# ── 配置热重载 ────────────────────────────────────────────

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        # 首次运行：从应用目录复制默认配置
        default_cfg = APP_DIR / "config.yaml"
        if default_cfg.exists():
            import shutil
            shutil.copy2(str(default_cfg), str(CONFIG_PATH))
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def normalize_base_url(url: str) -> str:
    """确保 base_url 以 /v1 结尾（DeepSeek 等兼容 API 需要）。"""
    url = url.rstrip('/')
    if not url.endswith('/v1'):
        url += '/v1'
    return url

# ── LLM 分类 ──────────────────────────────────────────────

CLASSIFY_PROMPT = """你是一个中文消息语义分类引擎。你的任务是理解消息的【真实意图】，而非做字面关键词匹配。

═══ 核心原则：理解语境，不要被字面词骗到 ═══

中文有大量的修辞手法、网络梗、成语、反讽，你必须理解上下文：
- "卖萌" ≠ 卖东西（是撒娇/装可爱）
- "卖队友" ≠ 卖东西（是游戏术语，指坑队友）
- "卖关子" ≠ 卖东西（是故意不说）
- "砸锅卖铁" ≠ 卖废铁（是成语，表示不惜代价）
- "买醉" ≠ 买东西（是喝酒解愁）
- "买单" ≠ 买东西（是结账/承担后果）
- "出卖" ≠ 出+卖（是背叛）
- "我裂开了" ≠ 物理破裂（是网络用语，表示崩溃）
- "绝绝子" ≠ 无意义（是夸赞/感叹）

判断 C 类（交易）的唯一标准：消息中是否包含【真实的、具体的买卖/交易意图】
- ✅ "出一个二手显示器，200块" → C（有具体物品和价格）
- ✅ "求购一台笔记本，预算5000" → C（有明确求购意图）
- ❌ "卖萌可耻" → B（是网络用语，不是交易）
- ❌ "我买醉了" → B（是情绪表达，不是购物）

═══ A 类：重要信息 ═══
仅限学校官方发布的正式通知：
- 考试安排、课程调整、放假通知、DDL
- 奖学金、评优、保研等官方政策
- 紧急安全事项

严禁归为 A：学生之间的讨论、个人观点、政治辩论

═══ B 类：校园轶事 ═══
- 校园趣闻、吐槽、日常分享、情感表达
- 学术讨论、课程评价、社团活动
- 网络梗、玩梗、meme
- 政治/历史/社会话题讨论
- 任何包含修辞手法的消息（如"卖萌""买醉"等）

═══ C 类：二手资讯 ═══
必须存在真实的交易意图：
- 明确的买卖、转让、求购（有具体物品/价格/交易条件）
- 虚拟服务：代课、代跑、跑腿、拼车、合租

═══ None 类：垃圾信息 ═══
- 纯表情、单字回复（嗯、哦、好、6）
- 纯情绪表达（哈哈、笑死、绝了）
- 无意义灌水、刷屏、复读

═══ 输出格式 ═══
严格返回 JSON：
{"category": "A/B/C/None", "summary": "一句话摘要", "tags": ["标签1", "标签2"]}"""

async def _call_llm(content: str, cfg: dict) -> dict:
    """实际的 LLM HTTP 调用，由 classify_message 通过 asyncio.wait_for 包装。"""
    llm = cfg.get("llm", {})
    api_key = llm.get("api_key", "")
    base_url = normalize_base_url(llm.get("base_url", "https://api.openai.com/v1"))
    model = llm.get("model", "gpt-4o-mini")

    if not api_key:
        print(f"  [WARN] 无 API Key，使用规则引擎降级", flush=True)
        return _rule_classify(content)

    url = f"{base_url}/chat/completions"
    # 分阶段超时：连接5s，读取8s，写入5s，连接池5s
    timeout = httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout, verify=True) as client:
        r = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": CLASSIFY_PROMPT},
                    {"role": "user", "content": content},
                ],
                "temperature": 0.1,
                "max_tokens": 200,
            },
        )
        if r.status_code != 200:
            print(f"  [LLM HTTP {r.status_code}] {r.text[:200]}", flush=True)
            return _rule_classify(content)

        data = r.json()
        text = data["choices"][0]["message"]["content"].strip()
        # 提取 JSON（兼容 ```json ... ``` 包裹）
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        return json.loads(text)


async def classify_message(content: str, cfg: dict) -> dict:
    """带 12 秒硬超时的 LLM 分类，超时直接降级到规则引擎。"""
    try:
        return await asyncio.wait_for(_call_llm(content, cfg), timeout=12.0)
    except asyncio.TimeoutError:
        print(f"  [LLM TIMEOUT] 12s 超时，降级到规则引擎", flush=True)
        return _rule_classify(content)
    except json.JSONDecodeError as e:
        print(f"  [LLM JSON ERROR] {e}", flush=True)
        return _rule_classify(content)
    except httpx.ConnectError as e:
        print(f"  [LLM CONNECT ERROR] {e}", flush=True)
        return _rule_classify(content)
    except httpx.ReadTimeout:
        print(f"  [LLM READ TIMEOUT]", flush=True)
        return _rule_classify(content)
    except Exception as e:
        print(f"  [LLM ERROR] {type(e).__name__}: {e}", flush=True)
        return _rule_classify(content)


def _rule_classify(content: str) -> dict:
    """降级规则引擎：基于关键词的简单分类。
    使用短语匹配而非单字匹配，避免「卖萌」被误判为二手。"""
    c = content.lower()

    # A 类：重要信息
    a_keywords = ["通知", "公告", "截止", "考试安排", "重要通知", "紧急通知", "ddl", "deadline",
                  "放假通知", "课程调整", "奖学金", "保研", "评优"]
    if any(kw in c for kw in a_keywords):
        return {"category": "A", "summary": content[:50], "tags": ["通知"]}

    # C 类：二手交易（用短语匹配，避免误判）
    c_phrases = [
        # 交易意图短语
        "出一个", "出一个", "出闲置", "出二手", "低价出", "便宜出", "忍痛出", "急出",
        "求购", "收一个", "收二手", "求一个",
        "转让", "转手", "转卖",
        "拼单", "代购", "闲置交易",
        # 虚拟服务
        "代课", "代跑", "代取", "代拿", "带饭", "帮取", "跑腿",
        "拼车", "拼房", "合租",
        # 明确的交易关键词组合
        "卖了", "买了", "卖掉", "买掉", "出售", "收购",
        "价格", "多少钱", "包邮", "不议价",
    ]
    # 排除词：包含这些词的短语不算交易
    exclude_words = ["卖萌", "卖关子", "卖队友", "卖国", "卖身", "买醉", "买单", "买账",
                     "卖力", "卖命", "买卖人", "卖弄", "买通"]
    if any(kw in c for kw in c_phrases) and not any(ex in c for ex in exclude_words):
        return {"category": "C", "summary": content[:50], "tags": ["二手"]}

    # B 类：校园轶事（长度要求，避免短消息误判）
    if len(content) > 15:
        b_keywords = ["宿舍", "食堂", "老师", "上课", "社团", "表白", "吐槽", "考试周",
                      "绩点", "学分", "选课", "图书馆", "实验", "论文", "答辩"]
        if any(kw in c for kw in b_keywords):
            return {"category": "B", "summary": content[:50], "tags": ["校园"]}

    return {"category": "None", "summary": "", "tags": []}


# ── 写入后端 ──────────────────────────────────────────────

async def ingest_message(msg: dict):
    url = f"{API_BASE}/api/ingest"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=msg, timeout=aiohttp.ClientTimeout(total=10)) as r:
                body = await r.text()
                if r.status == 200:
                    print(f"  [OK] {msg['category']}: {msg['summary'][:40]}", flush=True)
                else:
                    print(f"  [ERR] ingest {r.status}: {body[:200]}", flush=True)
    except Exception as e:
        print(f"  [ERR] ingest: {type(e).__name__}: {e}", flush=True)


async def buffer_message(msg: dict):
    url = f"{API_BASE}/api/buffer"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=msg, timeout=aiohttp.ClientTimeout(total=10)) as r:
                body = await r.text()
                if r.status == 200:
                    print(f"  [BUFFERED] {msg['raw_content'][:40]}", flush=True)
                else:
                    print(f"  [ERR] buffer {r.status}: {body[:200]}", flush=True)
    except Exception as e:
        print(f"  [ERR] buffer: {type(e).__name__}: {e}", flush=True)


async def archive_message(msg: dict):
    """零过滤全量落盘 — 无条件写入 raw_archive 表。"""
    url = f"{API_BASE}/api/archive_ingest"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=msg, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    body = await r.text()
                    print(f"  [ERR] archive {r.status}: {body[:200]}", flush=True)
    except Exception as e:
        print(f"  [ERR] archive: {type(e).__name__}: {e}", flush=True)


async def send_feishu_webhook(msg: dict, cfg: dict):
    """飞书 Webhook 实时暗影回传 — 异步发送，3秒超时，不阻塞主流程。"""
    feishu = cfg.get("feishu_sync", {})
    if not feishu.get("enable", False):
        return
    webhook_url = feishu.get("webhook_url", "")
    node_name = feishu.get("node_name", "未知节点")
    if not webhook_url:
        return
    chat_type_label = "群聊" if msg.get("chat_type") == "group" else "私聊"
    payload = {
        "msg_type": "text",
        "content": {
            "text": (
                f"[情报同步] [采集节点: {node_name}]\n"
                f"来源: {chat_type_label}-{msg.get('chat_name', '未知')}\n"
                f"发送人: {msg.get('sender_name', '未知')}\n"
                f"时间: {msg.get('created_at', '')}\n"
                f"正文: {msg.get('raw_content', '')}"
            )
        },
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=3),
            ) as r:
                if r.status != 200:
                    body = await r.text()
                    print(f"  [ERR] feishu {r.status}: {body[:100]}", flush=True)
    except asyncio.TimeoutError:
        print(f"  [ERR] feishu webhook 超时 (3s)", flush=True)
    except Exception as e:
        print(f"  [ERR] feishu: {type(e).__name__}: {e}", flush=True)


async def upload_to_mothership(msg: dict, cfg: dict):
    """将分类消息上传到 Vercel 母舰 — 异步发送，不阻塞主流程。"""
    ms = cfg.get("mothership", {})
    url = ms.get("url", "")
    if not url:
        return
    node_name = ms.get("node_name", "default")
    payload = {
        "node_name": node_name,
        "uin": "",
        "nickname": "",
        "messages": [{
            "msg_id": msg.get("msg_id", ""),
            "chat_type": msg.get("chat_type", "group"),
            "chat_name": msg.get("chat_name", ""),
            "sender_name": msg.get("sender_name", ""),
            "raw_content": msg.get("raw_content", ""),
            "category": msg.get("category", ""),
            "summary": msg.get("summary", ""),
            "tags": msg.get("tags", []),
            "created_at": msg.get("created_at", ""),
        }],
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{url}/api/ingest", json=payload,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as r:
                if r.status != 200:
                    body = await r.text()
                    print(f"  [ERR] mothership {r.status}: {body[:100]}", flush=True)
    except asyncio.TimeoutError:
        pass
    except Exception as e:
        print(f"  [ERR] mothership: {type(e).__name__}: {e}", flush=True)


# ── 主循环 ────────────────────────────────────────────────

async def main():
    cfg = load_config()
    ws_url = cfg.get("napcat", {}).get("ws_url", "ws://127.0.0.1:3001")
    group_filter = set(str(g) for g in cfg.get("napcat", {}).get("group_ids", []) or [])

    llm = cfg.get("llm", {})
    mode = cfg.get("scraper", {}).get("mode", "realtime")
    print(f"=== AI Scraper Agent ===", flush=True)
    print(f"Mode: {mode}", flush=True)
    print(f"WebSocket: {ws_url}", flush=True)
    print(f"LLM: {normalize_base_url(llm.get('base_url', '?'))} / {llm.get('model', '?')}", flush=True)
    print(f"API Key: {'***' + llm.get('api_key', '')[-4:] if llm.get('api_key') else 'NOT SET'}", flush=True)
    print(f"Group filter: {'ALL' if not group_filter else group_filter}", flush=True)
    print("", flush=True)

    msg_count = 0

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(ws_url, heartbeat=30) as ws:
                    print("[CONNECTED] NapCat WebSocket", flush=True)
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue

                        print(f"[DEBUG] 收到 ws 消息: {msg.data[:200]}", flush=True)

                        try:
                            data = json.loads(msg.data)
                        except json.JSONDecodeError:
                            print(f"[DEBUG] JSON 解析失败，跳过", flush=True)
                            continue

                        # 处理群消息和私聊消息（含自己发送的）
                        if data.get("post_type") not in ("message", "message_sent"):
                            print(f"[DEBUG] 非 message 类型: {data.get('post_type')}", flush=True)
                            continue
                        message_type = data.get("message_type")
                        if message_type not in ("group", "private"):
                            print(f"[DEBUG] 不支持的消息类型: {message_type}", flush=True)
                            continue

                        sender = data.get("sender", {})
                        sender_id = str(sender.get("user_id", ""))
                        sender_name = sender.get("card") or sender.get("nickname", "")
                        msg_id = str(data.get("message_id", ""))

                        # Bug2: Unix 时间戳 → UTC+8 字符串
                        raw_ts = data.get("time")
                        if raw_ts:
                            created_at = datetime.fromtimestamp(
                                int(raw_ts), tz=timezone(timedelta(hours=8))
                            ).strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            created_at = datetime.now(
                                tz=timezone(timedelta(hours=8))
                            ).strftime("%Y-%m-%d %H:%M:%S")

                        # 根据消息类型确定 chat_type / chat_id / chat_name
                        if message_type == "group":
                            chat_type = "group"
                            chat_id = str(data.get("group_id", ""))
                            chat_name = data.get("group_name", "")
                            if group_filter and chat_id not in group_filter:
                                print(f"[DEBUG] 群 {chat_id} 不在过滤列表中, 跳过", flush=True)
                                continue
                            print(f"[DEBUG] ✓ 群消息, group_id={chat_id}", flush=True)
                        else:
                            chat_type = "private"
                            chat_id = sender_id
                            chat_name = sender_name
                            print(f"[DEBUG] ✓ 私聊, sender_id={sender_id}", flush=True)

                        # 提取纯文本（跳过纯图片/表情）
                        raw = data.get("raw_message", "")
                        print(f"[DEBUG] raw_message={repr(raw)}", flush=True)
                        if not raw:
                            parts = []
                            for seg in (data.get("message") or []):
                                if seg.get("type") == "text":
                                    parts.append(seg.get("data", {}).get("text", ""))
                            raw = "".join(parts)
                            print(f"[DEBUG] 从 segments 提取: {repr(raw)}", flush=True)

                        if is_only_cq(raw):
                            print(f"[DEBUG] 纯 CQ 码消息, 跳过", flush=True)
                            continue

                        # 清理 CQ 码后提取文本
                        clean = strip_cq(raw)
                        print(f"[DEBUG] clean={repr(clean)}, len={len(clean)}", flush=True)
                        if len(clean) < 2:
                            print(f"[DEBUG] 文本过短, 跳过", flush=True)
                            continue

                        msg_count += 1
                        tag = "群聊" if chat_type == "group" else "私聊"
                        print(f"\n[MSG #{msg_count}] [{tag}:{chat_name}] {sender_name}: {clean[:60]}", flush=True)

                        # 零过滤全量落盘 — 无条件归档
                        archive_data = {
                            "msg_id": msg_id,
                            "chat_type": chat_type,
                            "chat_name": chat_name,
                            "sender_name": sender_name,
                            "raw_content": clean,
                            "created_at": created_at,
                        }
                        await archive_message(archive_data)
                        # 飞书 Webhook 实时回传（异步，不阻塞）
                        asyncio.create_task(send_feishu_webhook(archive_data, cfg))

                        # 热重载配置（每条消息重新读取）
                        cfg = load_config()
                        mode = cfg.get("scraper", {}).get("mode", "realtime")

                        if mode == "batch":
                            # batch 模式：写入缓冲池，不调 LLM
                            print(f"  [BATCH] 写入 raw_buffer...", flush=True)
                            await buffer_message({
                                "msg_id": msg_id,
                                "chat_type": chat_type,
                                "chat_id": chat_id,
                                "chat_name": chat_name,
                                "sender_id": sender_id,
                                "sender_name": sender_name,
                                "raw_content": clean,
                                "created_at": created_at,
                            })
                        else:
                            # realtime 模式：调 LLM 分类
                            llm_cfg = cfg.get("llm", {})
                            print(f"  [DEBUG] 准备请求 LLM, 模型名: {llm_cfg.get('model', '?')}", flush=True)
                            result = await classify_message(clean, cfg)
                            print(f"  [DEBUG] LLM 返回: {result}", flush=True)
                            cat = result.get("category", "None")
                            if cat == "None":
                                print(f"  [SKIP] 无意义闲聊", flush=True)
                                continue
                            print(f"  [DEBUG] 调用 ingest_message...", flush=True)
                            classified = {
                                "msg_id": msg_id,
                                "chat_type": chat_type,
                                "group_id": chat_id if chat_type == "group" else "",
                                "group_name": chat_name if chat_type == "group" else "",
                                "sender_id": sender_id,
                                "sender_name": sender_name,
                                "raw_content": clean,
                                "category": cat,
                                "summary": result.get("summary", ""),
                                "tags": result.get("tags", []),
                                "created_at": created_at,
                            }
                            await ingest_message(classified)
                            # 上传到母舰
                            asyncio.create_task(upload_to_mothership({
                                "msg_id": msg_id,
                                "chat_type": chat_type,
                                "chat_name": chat_name,
                                "sender_name": sender_name,
                                "raw_content": clean,
                                "category": cat,
                                "summary": result.get("summary", ""),
                                "tags": result.get("tags", []),
                                "created_at": created_at,
                            }, cfg))

        except Exception as e:
            print(f"\n[DISCONNECTED] {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
            print(f"  Reconnecting in 5s...", flush=True)
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
