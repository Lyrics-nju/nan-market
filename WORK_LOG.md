# 工作记录 — 2026-05-27

> 本文档记录了项目从单机版重构为 Vercel 多用户架构的全部工作内容。

---

## 一、Vercel 母舰后端 (`api/index.py`)

### 做了什么
新建了 Vercel Serverless API，作为数据汇聚的"母舰"。用户端采集的消息通过 HTTP POST 上传到这里，管理员通过 Web 界面查看所有用户的数据。

### 文件
- `api/index.py` — FastAPI 应用，包含以下端点：
  - `POST /api/ingest` — 接收用户端上传的分类消息
  - `GET /api/admin/messages` — 管理员查看所有消息（需 admin_key）
  - `GET /api/admin/users` — 查看所有注册节点
  - `GET /api/admin/stats` — 数据统计（按分类、按节点）
  - `GET /api/admin/export` — 数据导出（JSON/JSONL 格式，便于 AI 训练）
  - `GET /api/health` — 健康检查
- `api/requirements.txt` — Vercel Python 运行时依赖

### 原理
Vercel 的 `@vercel/python` 运行时会将 `api/index.py` 中的 FastAPI `app` 对象作为 Serverless Function 入口。每次 HTTP 请求触发一个函数实例，冷启动时重新初始化。当前使用内存存储，适合快速验证；生产环境建议迁移到 Vercel Postgres 或 Supabase。

### 存储策略
- **Vercel 环境**：内存存储，冷启动重置（可通过 `VERCEL` 环境变量检测）
- **本地开发**：自动持久化到 `data/messages.json` 文件
- **导出接口**：`/api/admin/export` 支持 JSON 和 JSONL 格式，方便导出训练数据

---

## 二、Vercel 部署配置 (`vercel.json`)

### 做了什么
配置了 Vercel 的路由规则，将 `/api/*` 请求转发到 Python Serverless Function，其余请求 serve 前端静态文件。

### 文件
- `vercel.json`

### 原理
```json
{
  "builds": [{"src": "api/index.py", "use": "@vercel/python"}],
  "routes": [
    {"src": "/api/(.*)", "dest": "api/index.py"},     // API 请求 → Python
    {"src": "/(.*)", "dest": "/frontend/dist/$1"}      // 其他 → 静态文件
  ]
}
```
Vercel 的路由系统按照顺序匹配规则。API 路由优先匹配，确保 `/api/*` 请求不会被静态文件处理器拦截。

---

## 三、用户端 API 改造 (`backend/api.py`)

### 做了什么
1. 新增母舰上传功能 (`upload_to_mothership`)
2. 配置模型增加 `mothership_url` 和 `node_name` 字段
3. 新增 `/api/mothership/sync` 手动同步端点
4. 新增 `/api/mothership/test` 连通性测试端点
5. 保留飞书接口但默认关闭
6. 全局异常捕获防止进程崩溃
7. NapCat 重启改为线程池执行，不阻塞事件循环

### 文件
- `backend/api.py` — 主要修改

### 原理

**母舰上传**：`upload_to_mothership()` 是一个异步函数，使用 `httpx` 向母舰 `/api/ingest` 发送 POST 请求。在 scraper 分类完成后通过 `asyncio.create_task()` 异步调用，不阻塞消息处理主流程。

**全局异常捕获**：FastAPI 的 `@app.exception_handler(Exception)` 装饰器捕获所有未处理异常，返回 500 错误而不是让 uvicorn 进程退出。异常信息同时打印到控制台和 `api.log` 文件。

**线程池重启**：`_restart_napcat_sync()` 内含 `time.sleep(3)` 阻塞调用。在 async handler 中直接调用会阻塞 uvicorn 的事件循环 3 秒，导致所有并发请求排队。改为 `loop.run_in_executor(None, _restart_napcat_sync)` 后，重启操作在独立线程中执行，事件循环不受影响。

---

## 四、Scraper 改造 (`backend/scraper.py`)

### 做了什么
1. 新增 `upload_to_mothership()` 函数
2. realtime 模式分类完成后自动上传到母舰
3. 飞书 webhook 默认关闭

### 文件
- `backend/scraper.py` — 主要修改

### 原理
消息处理流程变为：
```
WebSocket 消息 → 过滤 → 归档 → 飞书(可选) → LLM 分类 → 写入本地 DB → 上传母舰
```
上传母舰使用 `asyncio.create_task()` 异步执行，5 秒超时。即使母舰不可达，也不会影响本地消息采集。

---

## 五、前端改造 (`frontend/src/pages/LoginPage.tsx`)

### 做了什么
1. 新增"母舰地址"配置项（可选）
2. 新增"节点名称"配置项（可选）
3. 配置保存时同步提交 mothership_url 和 node_name
4. 页面加载时从后端读取已保存的母舰配置

### 文件
- `frontend/src/pages/LoginPage.tsx`

### 原理
配置通过 `POST /api/config` 提交，后端写入 `config.yaml`。母舰地址和节点名称是可选项，不填则不上传数据。这样用户可以选择纯本地使用，也可以选择同步到云端。

---

## 六、构建脚本改造 (`build_dist.py`)

### 做了什么
1. 分发包 config.yaml 清空敏感信息（API Key、飞书 webhook）
2. 新增 mothership 配置字段（url 为空，node_name 自动设置）
3. 保留内嵌 Python + NapCat 打包

### 文件
- `build_dist.py`

### 原理
分发包的 config.yaml 不再包含真实的 API Key 和 webhook URL。用户首次启动后在网页端自行填写。这样：
- 安全：不泄露开发者的密钥
- 灵活：每个用户用自己的 LLM 服务
- 可控：母舰地址由用户决定是否配置

---

## 七、环境变量脱敏

### 做了什么
1. 创建 `.env.example` — 环境变量模板
2. 创建 `backend/config.yaml.example` — 配置文件模板
3. Vercel API 的 `ADMIN_KEY` 从环境变量读取

### 文件
- `.env.example`
- `backend/config.yaml.example`

### 原理
`.gitignore` 排除了 `config.yaml` 和 `.env`，防止提交真实密钥。`.env.example` 和 `config.yaml.example` 作为模板提交到仓库，新用户复制后填写自己的值。

---

## 八、`.gitignore`

### 做了什么
排除了所有不适合提交到 Git 的文件。

### 排除项
| 类别 | 排除内容 | 原因 |
|------|----------|------|
| Python | `__pycache__/`, `venv/`, `python_embed/` | 运行时生成，可重建 |
| Node.js | `node_modules/` | 依赖目录，npm install 重建 |
| NapCat | `NapCat_Portable/` | 320MB 二进制文件，不适合 git |
| 数据库 | `*.db`, `*.sqlite` | 运行时数据 |
| 密钥 | `config.yaml`, `.env` | 包含 API Key 等敏感信息 |
| 构建 | `dist_output/`, `dist_output_v2/` | 打包输出 |
| 日志 | `*.log` | 运行时日志 |
| 备份 | `backup_*/` | 开发过程备份 |
| 数据 | `data/` | 母舰运行时数据 |

---

## 九、README.md

### 做了什么
编写了完整的项目文档，包含：
- 项目简介和架构图
- 核心功能列表
- 快速开始指南（用户端 + 母舰部署）
- 项目结构说明
- 技术栈表格
- API 接口文档
- 开发指南
- 合规声明
- 致谢

---

## 十、LICENSE (MIT)

### 做了什么
添加 MIT 开源许可证。

### 原理
MIT 是最宽松的开源许可证之一，允许任何人使用、修改、分发代码，只需保留版权声明。适合学术项目。

---

## 十一、GitHub Actions CI/CD

### 做了什么
1. `build.yml` — Release 构建流水线
2. `ci.yml` — PR 检查流水线

### 文件
- `.github/workflows/build.yml`
- `.github/workflows/ci.yml`

### 原理

**build.yml**（Release 触发）：
```
git tag v0.1.0 → git push --tags
→ GitHub Actions 启动 Windows runner
→ 安装 Node.js 20 + Python 3.11
→ npm ci (前端依赖)
→ npm run build (前端构建)
→ python build_dist.py (打包)
→ 上传 5 个 ZIP 到 GitHub Release
→ 可选：自动部署到 Vercel
```

**ci.yml**（PR 触发）：
```
PR 提交 → Ubuntu runner
→ 前端构建检查
→ Python 语法检查 (py_compile)
→ 确保代码无语法错误
```

---

## 十二、Vercel 数据持久化

### 做了什么
母舰 API 从纯内存存储改为双模式存储：
- **Vercel 环境**：内存存储（检测 `VERCEL` 环境变量）
- **本地开发**：自动持久化到 `data/messages.json`

新增 `/api/admin/export` 端点支持 JSON 和 JSONL 格式导出。

### 原理
Vercel Serverless Function 的文件系统是只读的（除了 `/tmp` 目录，有 512MB 限制且不持久）。当前方案：
1. 开发阶段：文件持久化够用
2. 生产环境：需要迁移到外部数据库
3. 导出功能：管理员可以随时导出全量数据作为备份

**推荐的生产数据库方案**：
- Vercel Postgres（Serverless PostgreSQL，有免费额度）
- Supabase（开源 Firebase 替代，免费额度更大）
- PlanetScale（MySQL 兼容，免费 hobby 计划）

---

## 十三、NapCat 配置与 QQ 同时在线

### 原理
NapCat 支持多种 QQ 登录协议：
- **Android Phone** — 默认，会挤掉其他手机端
- **Android Pad** — 不挤掉 PC 端，推荐
- **iPad** — 不挤掉 PC 端，推荐
- **Watch** — 手表端，功能有限

同时在线的关键是选择 **Android Pad** 或 **iPad** 协议登录。NapCat WebUI 登录时可以选择设备类型。

### 当前状态
NapCat v4.x 默认支持多设备同时在线。用户在扫码登录时，NapCat WebUI 会提示选择设备类型。选择 Android Pad 或 iPad 即可与 PC 端 QQ 同时在线。

---

## 十四、后续修改（根据用户反馈）

### 1. 飞书重新开启
将 `config.yaml` 中 `feishu_sync.enable` 改回 `true`。用户需要先在本地验证飞书消息接收是否正常。

### 2. README 隐私描述修正
- 移除"管理员查看所有用户采集的消息数据"等描述
- 移除母舰 API 的管理员查询端点说明
- 改为中性的"云端同步"描述
- 强调全量消息采集（群聊 + 私聊 + 自己发送的）

### 3. 消息采集范围确认
scraper.py 已支持：
- `message_type == "group"` — 群聊消息
- `message_type == "private"` — 私聊消息
- `post_type == "message_sent"` — 自己发送的消息
- 未来可扩展 QQ 频道消息

### 4. 关于"纯网页版"的说明
NapCat 的"网页版"是指管理界面（WebUI）是网页，但 QQ 协议引擎仍需持续运行的 Node.js 进程。浏览器无法直接运行 QQ 的二进制协议。要实现"打开网址就能用"，需要将 NapCat 部署在云服务器上，用户通过网页远程操作。当前方案为下载即用（内嵌所有依赖），是零安装体验的最简方案。

---

## 发现的待改进项

1. **Vercel 内存存储**：冷启动会丢数据。建议下一阶段接入 Supabase 或 Vercel Postgres。
2. **用户认证**：当前母舰只有 admin_key 验证，没有用户注册/登录系统。如果多用户正式使用，需要加 JWT 认证。
3. ~~**消息去重**~~ ✅ 已修复：母舰 `/api/ingest` 基于 `msg_id` 去重，重复上传自动跳过。
4. ~~**Rate Limiting**~~ ✅ 已修复：母舰 API 添加滑动窗口限流（60 次/分钟/IP）。
5. **HTTPS 本地开发**：localhost 使用 HTTP，QQ 扫码可能要求 HTTPS（部分浏览器安全策略）。
6. ~~**NapCat 自动启动**~~ ✅ 已修复：launch.bat 改用 `start /b` 后台启动 NapCat，窗口关闭不终止进程。EXE 版 launcher.py 已内置进程管理。
7. ~~**日志轮转**~~ ✅ 已修复：`api.log` 改用 `RotatingFileHandler`（单文件 5MB，保留 3 个备份）。
8. ~~**前端路由**~~ ✅ 已确认：SPA catch-all 已在所有 API 路由之后定义，添加注释说明。
9. ~~**config.yaml 敏感信息**~~ ✅ 已修复：构建脚本（build_dist.py / build_exe.py）自动生成随机 `admin_key` 和 `webui_token`，config.yaml.example 改为占位符。

---

## 十五、Bug 修复：batch_process 母舰上传缺失

### 问题
`/api/batch_process` 端点在批量分类消息写入数据库后，没有调用 `upload_to_mothership()` 将数据同步到母舰。这意味着 batch 模式下采集的消息永远不会上传到 Vercel 母舰。

### 修复
在 `batch_process` 函数中，清空 raw_buffer 之前，添加了母舰上传逻辑：
```python
if all_topics:
    cfg = load_config()
    ms_msgs = []
    for t in all_topics:
        if t.get("category") == "None":
            continue
        ms_msgs.append({...})
    if ms_msgs:
        asyncio.create_task(upload_to_mothership(ms_msgs, cfg))
```

### 原理
`asyncio.create_task()` 确保上传在后台异步执行，不阻塞 batch_process 的返回。即使母舰不可达，也不会影响本地数据处理。

---

## 十六、EXE 打包 (PyInstaller)

### 做了什么
新增 PyInstaller EXE 打包方案，与现有 ZIP 分发包并存：
1. `launcher.py` — 主启动器，管理所有子进程
2. `build_exe.py` — EXE 构建脚本
3. 更新 `api.py` 和 `scraper.py` 支持 `AI_CONSOLE_BASE` 环境变量

### 文件
- `launcher.py` — EXE 启动器入口
- `build_exe.py` — PyInstaller 构建脚本

### 架构
```
AI_Console_EXE/
├── AI_Console_Launcher.exe   ← 用户双击启动
├── api_server.exe            ← FastAPI 服务器
├── scraper_agent.exe         ← 消息采集 + LLM 分类
├── NapCat_Portable/          ← QQ 协议引擎 (Node.js)
├── dist/                     ← 前端静态文件
├── config.yaml               ← 用户配置
├── market.db                 ← SQLite 数据库
├── api.py, scraper.py        ← 源码备份（调试用）
└── 使用说明.txt
```

### 原理
**PyInstaller --onefile**：将 Python 解释器和所有依赖打包为单个 EXE。运行时解压到临时目录执行。

**进程管理**：`launcher.py` 启动三个进程：
1. NapCat (Node.js) — 独立的 Node.js 进程
2. API Server (Python) — uvicorn + FastAPI
3. Scraper Agent (Python) — WebSocket 监听 + LLM 分类

**路径解析**：通过 `AI_CONSOLE_BASE` 环境变量解决 PyInstaller 打包后的路径问题。launcher 在启动子进程时设置此变量，api.py 和 scraper.py 优先读取此变量确定工作目录。

**退出清理**：launcher 注册了 SIGINT/SIGTERM/SIGBREAK 信号处理器，确保关闭窗口时所有子进程被正确终止。

### 构建产物
| 文件 | 大小 | 说明 |
|------|------|------|
| AI_Console_Launcher.exe | ~9MB | 主启动器 |
| api_server.exe | ~39MB | API 服务器 |
| scraper_agent.exe | ~36MB | Scraper |
| NapCat_Portable/ | ~320MB | QQ 协议 |
| AI_Console_EXE.zip | ~196MB | 完整分发包 |

---

## 文件变更清单

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `api/index.py` | Vercel 母舰 Serverless API |
| 新建 | `api/requirements.txt` | Vercel Python 依赖 |
| 新建 | `vercel.json` | Vercel 部署配置 |
| 新建 | `.gitignore` | Git 排除规则 |
| 新建 | `.env.example` | 环境变量模板 |
| 新建 | `backend/config.yaml.example` | 配置文件模板 |
| 新建 | `README.md` | 项目文档 |
| 新建 | `LICENSE` | MIT 许可证 |
| 新建 | `.github/workflows/build.yml` | Release 构建流水线 |
| 新建 | `.github/workflows/ci.yml` | CI 检查流水线 |
| 新建 | `WORK_LOG.md` | 本工作记录 |
| 新建 | `launcher.py` | EXE 启动器 |
| 新建 | `build_exe.py` | PyInstaller EXE 构建脚本 |
| 修改 | `backend/api.py` | 母舰上传、配置扩展、异常捕获、线程池重启、batch 母舰上传修复、AI_CONSOLE_BASE 路径 |
| 修改 | `backend/scraper.py` | 母舰上传、飞书默认关闭、AI_CONSOLE_BASE 路径 |
| 修改 | `backend/config.yaml` | 飞书默认关闭 |
| 修改 | `frontend/src/pages/LoginPage.tsx` | 母舰地址、节点名称配置 |
| 修改 | `build_dist.py` | 清空敏感信息、母舰配置 |
| 修改 | `.gitignore` | 排除 dist_output_exe/ 和 _build_pyinstaller/ |
