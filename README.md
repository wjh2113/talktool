# TalkTool · AI 语音沟通训练

沟通表达演练场：选一个场景（临时点名发言、平息客户怒火……），AI 扮演对手角色和你**纯语音**对练，结束后生成评估报告，所有训练可回看。

**使用说明（学员 / 管理员）** → [`docs/操作手册.md`](docs/操作手册.md)

```
talktool/
├── backend/                 FastAPI + SQLite
│   ├── app/
│   │   ├── main.py          路由
│   │   ├── config.py        环境变量
│   │   ├── db.py            建表 / 种子数据 / 时间工具
│   │   ├── schema.sql       建表 SQL
│   │   ├── seed.sql         内置数据 SQL（9 分类 / 49 个场景大类 / 98 个训练 / 96 个表达框架）
│   │   ├── seed_more.py     第二批内置场景
│   │   ├── seed_more2.py    第三批内置场景（新增场景写这里，每个训练带推荐框架 + 常见误区）
│   │   ├── frameworks_data.py  表达框架库（改框架内容改这里）
│   │   ├── frameworks_ip.json  自媒体助手的 32 个创作框架（由 BUILTIN-FRAMEWORKS.md 转换）
│   │   ├── guides_data.py   前两批训练的推荐框架 + 场景示例 + 常见误区
│   │   ├── seed_data.py     种子数据源（改场景内容改这里）
│   │   └── services/
│   │       ├── gateway.py   AIapiMgr 网关客户端（chat / transcribe / tts）
│   │       ├── voice.py     语音对话服务：方案B 已实现，方案A 预留，Mock
│   │       ├── prompts.py   场景 System Prompt 模板 + 报告 Prompt
│   │       ├── report.py    报告生成 + too_short / abandoned 边界规则
│   │       ├── sessions.py  训练会话 / 报告 / 记录（与框架无关）
│   │       ├── metrics.py   表达数据：语速、口头禅、停顿、反应时间
│   │       ├── practice.py  跟读：示范稿 + 发音评测
│   │       ├── library.py   练习本 + 自定义场景
│   │       └── frameworks.py 表达框架库：列表 / 详情 / 场景关联
│   ├── scripts/check_gateway.py   网关连通性自检
│   └── tests/                     test_flow.py 全流程 · test_features.py 新功能 + 旧库升级 · test_auth.py 账号 · test_frameworks.py 框架库
└── frontend/                uni-app (Vue3)：H5 + 微信小程序
    └── src/
        ├── pages/           scenes(P1) scenario(P2) drill(P3) train(P4) report(P5) records(P6)
        │                    + 首页 / 练习本 / 我的 / readalong 跟读 / custom 自定义场景
        │                    + frameworks 框架库 / framework 框架详情
        ├── components/ReadAloud   听示范 + 跟读打分（报告、练习本、跟读页共用）
        └── utils/voice.js   录音 + VAD + 播放（H5 / 小程序双端）
```

## 1. 启动后端

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# .env 已经写好了你的租户和 Key（talktool）；如需重建：cp .env.example .env
python3 scripts/check_gateway.py      # 先确认网关的 chat / tts / speech 三个能力都通
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- 首次启动自动建库（`backend/data/talktool.db`）并写入 98 个内置训练和 96 个表达框架。之后每次启动都会按标题补上代码里新增的场景、按 code 更新框架内容和场景的推荐框架（已部署的库也会自动更新，训练记录不受影响）。
- 接口文档：http://127.0.0.1:8000/docs
- `.env` 里 `GATEWAY_API_KEY` 留空 = **Mock 模式**：不调网关，可走通全部页面和报告（AI 用固定台词）
- 测试：`python3 -m tests.test_flow && python3 -m tests.test_features && python3 -m tests.test_auth && python3 -m tests.test_frameworks`

## 2. 启动前端

```bash
cd frontend
npm install
npm run dev:h5            # 浏览器打开 http://localhost:5173
npm run dev:mp-weixin     # 用微信开发者工具导入 frontend/dist/dev/mp-weixin
npm run build:app         # 生成 App 资源（打 APK 前先跑；见下方「打包 App」）
```

- **H5**：`/api` 和 `/media` 由 vite 代理到 `127.0.0.1:8000`。麦克风要求 HTTPS 或 localhost，电脑浏览器直接用 localhost 即可；手机上测要走 HTTPS 隧道（如 `cloudflared tunnel --url http://localhost:5173`）。
- **小程序**：新建 `frontend/.env`，写入 `VITE_API_BASE=http://你的电脑局域网IP:8000`。开发者工具里勾选“不校验合法域名”；真机/上线需要 HTTPS 域名，并在小程序后台配置隐私协议（麦克风）。
- **打包 App（对齐小树学堂）**：生产 API 在 `frontend/.env.production`（`VITE_API_BASE=https://talk.aidigitcloud.cn`）。先到 [DCloud 开发者中心](https://dev.dcloud.net.cn/) 创建应用，把 `__UNI__xxxxxx` 填进 `frontend/src/manifest.json` 的 `appid`。然后二选一：
  - **云打包（推荐）**：HBuilderX 打开 `frontend` → 发行 → 原生 App-云打包 → Android，下载 `.apk` 安装。
  - **本地离线 SDK**：步骤与自检见 [`scripts/build-android-local.md`](scripts/build-android-local.md)、`./scripts/check-android-local.sh`（与小树同一套流程，不要照搬 Capacitor）。
- 如果 `npm install` 报 `@dcloudio` 版本问题：执行 `npx @dcloudio/uvm@latest` 对齐版本，或用 `npx degit dcloudio/uni-preset-vue#vite` 生成官方模板后把 `src/` 拷进去。

## 3. 网关对接（AIapiMgr）

| 环节 | 接口 | capability |
|---|---|---|
| AI 对练回复 | `POST /api/ai/chat` | `fast-chat`（低延迟） |
| 训练报告 | `POST /api/ai/chat` | `quality-chat` |
| 语音识别 | `POST /api/ai/transcribe`（multipart，WAV 16k） | `speech` |
| 语音合成 | `POST /api/ai/tts`（mp3） | `tts` |
| 跟读打分 | `POST /api/ai/pronounce` | `pronunciation` |
| 自定义场景 / 示范稿 | `POST /api/ai/chat` | `quality-chat` |

Key 只在后端 `.env`，前端拿不到。租户要在网关「租户配额 → 能力」里开通这 5 个能力（含 `pronunciation`）；如果开了 IP 白名单，记得加上服务器出口 IP。音色在 `.env` 的 `TTS_VOICE` 里改。

## 4. 一轮对话怎么跑

```
AI 讲话中（播放 TTS） → 可以说话（自动开麦） → 用户讲话中（VAD 检测）
  → 静音 1.4 秒自动发送（或点麦克风手动结束） → AI 思考中（识别 + 生成 + 合成） → AI 讲话中 …
点「结束训练」→ 判定状态 → completed 时调用 quality-chat 生成 JSON 报告
```

报告规则（`.env` 可调）：
- 中途退出且一句没说 → `abandoned`（主动放弃）
- 时长 < `MIN_DURATION_SEC`（默认 60 秒）或用户没发言 → `too_short`（时长过短）
- 其他 → `completed`，四维打分（逻辑表达 / 语言组织 / 应变能力 / 情绪管理）+ 亮点 + 建议 + 详细点评
- 超过 `STALE_SESSION_MIN` 未结束的会话自动记为主动放弃

页面上的「xx ms」是到后端的网络往返延迟，每 3 秒刷新一次。

## 5. 方案 A（实时语音）怎么接

`backend/app/services/voice.py` 里的 `RealtimeVoiceProvider` 是预留位，注释写了接入步骤：前端改为 WebSocket 推 16k PCM 帧，后端中继到实时语音 API，转写文本照样写进 transcript。会话、计时、报告逻辑不用改。设置 `VOICE_PROVIDER=realtime` 启用。

## 6. 练习闭环功能

| 功能 | 入口 | 说明 |
|---|---|---|
| 逐句复盘 + 示范 | 训练报告 → 逐句复盘 | 报告对用户每句话给出“更好的说法”和一句点拨，可听示范、跟读打分 |
| 练习本 | 底部 Tab「练习本」 | 报告里 ☆ 收藏话术/建议、跟读页收藏示范稿；可反复跟读，记录最高分 |
| 进步对比 | 训练报告 | 同一场景上次的总分和四维分对比（↑/↓），场景页显示练习次数与最高分 |
| 表达数据 | 训练报告 → 表达数据 | 语速（字/分）、开口反应时间、口头禅次数与高频词、≥0.8 秒的长停顿；后端从录音直接计算，不调大模型，也会喂给报告点评 |
| 跟读模式 | 场景介绍页「跟读示范」 | AI 为场景写一段示范稿（缓存），先听后读，网关 `pronunciation` 打分并标出没念准的句子 |
| 自定义场景 | 首页 / 我的 → 自定义场景 | 用户描述真实情况 + 选对方态度，AI 生成角色、背景、开场白，并从框架库挑 1–3 个推荐框架、写好常见误区，马上可以练；只对本人可见，每人最多 30 个 |
| 表达框架库 | 首页「表达框架库」/ 场景介绍页 | 见下方 6.1 |

**升级已部署的服务**：直接重新部署即可。后端启动时会自动给旧库补列、建 `note` 表、建“我的场景”系统分类，原有训练记录不受影响。部署前在网关给 talktool 租户勾选 `pronunciation` 能力，然后在 backend 目录跑一下 `python3 scripts/check_gateway.py`。

### 6.1 表达框架库

96 个说话套路，分 9 类：结构表达、即兴与当众、向上沟通、团队管理、情绪与关系、社交破冰、说服与谈判、求职面试、自媒体创作。内容来自三份资料（为人处世 / 职场生活 / 谈判，标注 A / C / D）、日常常用框架（PREP、SCQA、STAR、非暴力沟通……）以及自媒体助手的 32 个创作框架（`source=自媒体助手`，PREP/SCQA/STAR/金字塔 4 个重复的已合并进同名框架）。

- **框架库页**：分类筛选 + 搜索；**框架详情**：步骤拆解、适用场合、示例（可听示范、跟读打分、收藏到练习本）、常见误区、使用技巧，以及“去这些场景里练”（每个场景里这个框架该怎么说）。
- **场景介绍页**：每个训练都有「推荐表达框架」（步骤 + 本场景示例说法）和「常见误区」。
- **训练中**：底部「框架提示」可以打开一张小抄，只显示框架步骤。
- **报告**：AI 点评会判断你有没有用上推荐框架；报告底部「对照表达框架复盘」列出框架与误区。
- 改内容：框架改 `frameworks_data.py`，场景关联改 `guides_data.py` / `seed_more2.py` 的 `guide`，重启即同步。

## 7. 省 Token 与防刷

| 措施 | 配置（backend/.env） |
|---|---|
| 场景固定开场白的语音按文字缓存，同一场景只合成一次 | — |
| 录音里有效人声不足 300ms（噪声、误触）不送识别 | `ASR_MIN_SPEECH_MS` |
| 逐句复盘改为在报告里点开时才生成，生成后缓存 | `REVIEW_CAPABILITY=fast-chat` |
| 对练只带最近 6 轮对话 + 精简后的角色设定 | `HISTORY_TURNS` |
| 对练回复输出上限 150、报告 1200 | `REPLY_MAX_TOKENS` `REPORT_MAX_TOKENS` |
| 用户只说了 ≤3 句的短训练，报告用 fast-chat | `SHORT_REPORT_TURNS` |
| 对话 / 识别 / 报告 / 示范稿 / 自定义场景都带幂等键 `idempotencyKey`；遇到 429/502/503/504 或网络异常，用同一个键自动重试一次，不重复扣积分 | — |
| 每次大模型调用带 `maxCostCny` 单次成本上限 | `MAX_COST_REPLY` `MAX_COST_REPORT` `MAX_COST_OTHER`（留空 = 不限） |
| 每个用户、每个 IP 每天能开始的训练数 | `DAILY_SESSION_LIMIT=30` `DAILY_IP_SESSION_LIMIT=100`（0 = 不限） |

成本上限的默认值是估的：上线后看后端日志里每次调用的 `points=`，再把上限调到实际花费的 2~3 倍。按 IP 限额依赖 nginx 传真实 IP + uvicorn `--proxy-headers`（部署脚本已配好）。

## 8. 账号与邀请码

- 所有接口都需要登录（`/api/health`、`/api/ping` 除外）。用户名 + 密码登录，令牌 30 天有效（`TOKEN_DAYS`）。
- **管理员**：在 `backend/.env` 写上 `ADMIN_USERNAME` / `ADMIN_PASSWORD`，后端启动时如果这个用户不存在就自动创建（不会覆盖已有密码）。也可以在服务器上执行：
  ```bash
  cd /opt/talktool/backend
  .venv/bin/python -m app.admin create-admin boss 你的密码   # 创建或重置管理员
  .venv/bin/python -m app.admin invite 5 1 30                # 生成 5 个邀请码，各用 1 次，30 天有效
  .venv/bin/python -m app.admin users                        # 查看用户
  ```
- **邀请码**：管理员登录后在「我的 → 管理后台」生成（数量、每个可用次数、有效天数、备注），可复制邀请码或 H5 注册链接（`/#/pages/login/login?code=XXXX`，打开自动填好邀请码），也能停用。
- **用户管理**：管理后台可查看用户的训练次数、最近登录，停用（立即下线）/ 启用账号，重置密码（生成一次性临时密码）。
- **老数据**：上线账号前在某台设备上练过的记录，用这台设备注册时会自动归到新账号。
- **防暴力破解**：同一 IP 15 分钟内登录 / 注册失败 10 次会被暂时锁定（`LOGIN_FAIL_LIMIT`）。

## 9. 稳定性与成本

- **防刷**：每个账号每天的示范朗读、跟读评测、自定义场景、复盘 / 示范稿 / 重新生成报告都有上限（`DAILY_*_LIMIT`），单场训练最多 30 轮发言（`MAX_USER_TURNS`）。示范朗读只能读系统生成过的内容（本人的收藏、报告里的逐句示范、场景示范稿），不能拿来合成任意文字。
- **报告异步生成**：点“结束训练”立刻进入报告页，报告在后台生成，页面自动刷新；失败可以重新生成。服务重启时中断的报告会标记为失败。
- **音频清理**：后端每 6 小时清理一次：对话里的 AI 语音保留 7 天（`AUDIO_RETENTION_DAYS`），缓存的开场白 / 示范语音 180 天没人用才删（`TTS_CACHE_DAYS`）；同时清理过期令牌和旧计数。
- **nginx 直出音频**：生产环境 `/media/audio/` 由 nginx 直接读 `backend/data/audio`，不经过 Python（见 `deploy/nginx-talktool.conf`，部署脚本会放开目录读权限）。
- **SQLite WAL**：启动时开启 WAL 模式，读写互不阻塞，并发请求下不再容易出现 “database is locked”。

## 10. MVP 未做

微信一键登录 / 手机号登录（目前是用户名密码 + 邀请码）、支付、分享、排行榜。公共场景批量更新请用管理后台「场景导入」（Markdown/ZIP），见 [`docs/场景库导入格式.md`](docs/场景库导入格式.md)。

## 11. 文档索引

| 文档 | 用途 |
|---|---|
| [`docs/操作手册.md`](docs/操作手册.md) | 学员与管理员日常操作 |
| [`docs/场景库导入格式.md`](docs/场景库导入格式.md) | 导入文件格式 |
| [`docs/场景库导入-发给大模型的提示词.md`](docs/场景库导入-发给大模型的提示词.md) | 交给其他大模型整理题库 |
| [`docs/产品需求.md`](docs/产品需求.md) | 产品规格 |
| [`docs/AIapiMgr接入指南.md`](docs/AIapiMgr接入指南.md) | 网关对接 |
