# AI 社群情报控制台

> 基于 LLM 的 QQ 消息实时分类与情报采集系统 — 桌面客户端

## 简介

AI 社群情报控制台是一个端到端的消息采集、分类和分析系统。它通过 NapCat（QQ 协议框架）接入 QQ，采集所有接收到的消息（群聊、私聊），利用大语言模型对消息进行智能三分类（A 重要通知 / B 校园轶事 / C 二手资讯），将结果存储到本地数据库，同时支持推送到飞书机器人和云端同步。

客户端采用 pywebview 原生窗口，一键启动所有服务，无需浏览器依赖。

## 核心功能

- **全量消息采集**：通过 NapCat 接入 QQ，采集群聊、私聊、自己发送的消息
- **LLM 智能分类**：A（重要通知）、B（校园轶事）、C（二手资讯）三分类，支持 DeepSeek / OpenAI / Claude
- **实时/批量模式**：支持实时逐条分类或攒批后一次性处理
- **消息看板**：仪表盘实时统计 + 消息中心分类浏览 + 收藏夹管理
- **周报生成**：基于 LLM 自动生成每周情报摘要
- **飞书 Webhook**：分类结果实时推送到飞书机器人
- **云端同步**：可选将采集数据同步到 Vercel 母舰
- **桌面客户端**：pywebview 原生窗口，一键启动（NapCat + API + Scraper）
- **安装程序**：Inno Setup 安装包，点 Next 即可安装，桌面快捷方式
- **数据持久化**：用户数据存 `%APPDATA%/AIConsole/`，更新不丢失

## 快速开始

### 方式一：安装程序（推荐）

1. 从 [Releases](../../releases) 下载 `AIConsole_Setup_x.x.x.exe`
2. 双击安装程序 → Next → 选择目录 → Install
3. 桌面出现「AI 社群情报控制台」图标，双击启动
4. 填写 LLM API Key → 扫码登录 QQ → 自动开始采集

### 方式二：便携版

1. 从 [Releases](../../releases) 下载 ZIP 包
2. 解压到任意目录
3. 双击 `AI_Console_Launcher.exe`

**系统要求**：Windows 10/11 x64，无需安装 Python 或 Node.js

## 架构

```
┌─────────────────────────────────────────────────┐
│                 用户本地 (一键启动)                │
│                                                  │
│  ┌──────────────┐    ┌────────────────────────┐  │
│  │  pywebview   │    │    FastAPI Server      │  │
│  │  原生窗口     │◄──►│    (localhost:8000)    │  │
│  │  React SPA   │    │  静态文件 + REST API    │  │
│  └──────────────┘    └────────────────────────┘  │
│                                                  │
│  ┌──────────────┐    ┌────────────────────────┐  │
│  │    NapCat     │    │     Scraper Agent      │  │
│  │  QQ 协议引擎  │◄──►│  WS 监听 → LLM 分类   │  │
│  │  (port 6099)  │    │  → SQLite / 飞书 / 母舰 │  │
│  └──────────────┘    └────────────────────────┘  │
│                                                  │
│  用户数据: %APPDATA%/AIConsole/                   │
│  ├── market.db        (消息数据库)                │
│  └── config.yaml      (用户配置)                  │
└─────────────────────────────────────────────────┘
```

## 项目结构

```
nan-market/
├── backend/                    # 后端服务
│   ├── api.py                 # FastAPI 服务器（REST API + SSE + 静态文件托管）
│   ├── scraper.py             # WebSocket 消息监听 + LLM 分类引擎
│   ├── config.yaml.example    # 配置模板
│   └── requirements.txt
├── frontend/                   # React 前端
│   ├── src/
│   │   ├── pages/
│   │   │   └── LoginPage.tsx       # LLM 配置 + QQ 登录
│   │   └── components/
│   │       ├── DashboardPage.tsx   # 仪表盘（统计 + 服务状态 + 最新消息）
│   │       ├── MessagesPage.tsx    # 消息中心（分类浏览 + 搜索 + 收藏）
│   │       ├── BookmarksPage.tsx   # 收藏夹管理
│   │       ├── ReportsPage.tsx     # 周报生成
│   │       ├── SettingsPage.tsx    # 系统设置
│   │       ├── Layout.tsx          # 主布局（侧边栏 + 内容区）
│   │       └── ProtectedRoute.tsx  # 登录路由守卫
│   └── dist/                  # 构建输出（已包含在仓库中）
├── api/                        # Vercel 云端 Serverless API（母舰）
│   ├── index.py
│   └── requirements.txt
├── launcher.py                 # 桌面客户端启动器（PyInstaller 入口）
├── build_exe.py                # EXE 打包脚本
├── installer.iss               # Inno Setup 安装程序脚本
├── fetch_napcat.py             # NapCat 下载脚本
├── vercel.json                 # Vercel 部署配置
└── .gitignore
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18 + TypeScript + Vite + Tailwind CSS |
| 桌面客户端 | pywebview（Edge Chromium 内核） |
| 后端 | Python FastAPI + SQLite + aiohttp |
| QQ 协议 | NapCat（OneBot11 WebSocket） |
| LLM | OpenAI API 兼容（DeepSeek / Claude / GPT） |
| 消息推送 | 飞书 Webhook |
| 打包分发 | PyInstaller + Inno Setup |

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/services` | 各服务运行状态 |
| GET/POST | `/api/config` | 配置管理 |
| GET | `/api/qrcode` | 获取 QQ 登录二维码（PNG） |
| GET | `/api/login/status` | QQ 登录状态（轮询） |
| POST | `/api/login/password` | 密码登录 |
| POST | `/api/login/reset` | 重置登录缓存 |
| GET | `/api/stats` | 消息统计 |
| GET | `/api/messages` | 查询已分类消息（支持筛选/搜索/分页） |
| DELETE | `/api/messages/{id}` | 删除消息 |
| POST | `/api/bookmarks` | 添加收藏 |
| GET | `/api/bookmarks` | 查询收藏 |
| GET | `/api/weekly_summary` | 生成/获取周报 |
| GET | `/api/stream` | SSE 实时消息推送 |
| POST | `/api/batch_process` | 批量处理缓冲池 |
| POST | `/api/restart-napcat` | 重启 NapCat |

## 开发

```bash
# 后端
cd backend
pip install -r requirements.txt
python api.py                # 启动 API 服务器 (localhost:8000)
python scraper.py            # 启动消息采集器

# 前端
cd frontend
npm install
npm run dev                  # 开发模式 (localhost:5173)
npm run build                # 构建生产版本

# 打包 EXE
python build_exe.py          # 生成 dist_output_exe/

# 打包安装程序
# 用 Inno Setup 打开 installer.iss → Build → Compile
```

## 数据持久化

用户数据存储在 `%APPDATA%/AIConsole/`：

| 文件 | 说明 |
|------|------|
| `market.db` | 消息数据库（SQLite） |
| `config.yaml` | 用户配置（API Key、NapCat 设置等） |

- 更新安装时**不会覆盖**已有数据
- 卸载时会提示是否保留数据
- 开发模式下数据存储在项目根目录
- 每个用户通过昵称隔离数据，只能看到自己的消息

## 飞书 Webhook 配置

飞书 Webhook 可以让你在飞书群里实时收到采集到的消息推送。

### 步骤

1. **创建飞书机器人**
   - 打开飞书，进入你想接收消息的群
   - 点击群设置 → 群机器人 → 添加机器人
   - 选择「自定义机器人」
   - 填写机器人名称（如「情报助手」）
   - 点击「添加」

2. **复制 Webhook 地址**
   - 创建完成后会显示一个 Webhook 地址，格式如：
     ```
     https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
     ```
   - 复制这个地址

3. **在控制台中配置**
   - 打开 AI 社群情报控制台
   - 进入「设置」页面
   - 找到「飞书同步」选项，开启它
   - 粘贴刚才复制的 Webhook 地址
   - 点击保存

4. **测试**
   - 配置完成后，新采集到的消息会自动推送到飞书群
   - 推送格式：`[情报同步] 来源: 群聊-xxx / 发送人: xxx / 正文: xxx`

### 注意事项

- Webhook 地址包含敏感信息，请勿泄露
- 每个群可以创建多个机器人，但建议只用一个
- 飞书 Webhook 有频率限制（每分钟最多 5 条），高频消息可能会被合并
- 如果不需要飞书推送，保持关闭即可，不影响其他功能

## 合规声明

- 本项目使用的 NapCat 是基于 QQNT 协议的开源实现，仅供学习和研究用途
- 请遵守 QQ 的服务条款和相关法律法规
- 不得将本项目用于任何商业用途或侵犯他人隐私的行为
- 使用者需自行承担因使用本项目而产生的一切风险和责任

## License

[MIT](LICENSE)

## 致谢

- [NapCat](https://github.com/NapNeko/NapCatQQ) — QQ 协议框架
- [FastAPI](https://fastapi.tiangolo.com/) — Python Web 框架
- [React](https://react.dev/) — 前端框架
- [pywebview](https://pywebview.flowrl.com/) — 桌面窗口框架
- [Inno Setup](https://jrsoftware.org/isinfo.php) — Windows 安装程序
