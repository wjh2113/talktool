# TalkTool · AI 语音沟通训练

沟通技巧的“健身房”：选一个场景（临时点名发言、平息客户怒火……），AI 扮演对手角色和你**纯语音**对练，结束后生成评估报告，所有训练可回看。

```
talktool/
├── backend/                 FastAPI + SQLite
│   ├── app/
│   │   ├── main.py          路由
│   │   ├── config.py        环境变量
│   │   ├── db.py            建表 / 种子数据 / 时间工具
│   │   ├── schema.sql       建表 SQL
│   │   ├── seed.sql         种子数据 SQL（8 分类 / 21 场景）
│   │   ├── seed_data.py     种子数据源（改场景内容改这里）
│   │   └── services/
│   │       ├── gateway.py   AIapiMgr 网关客户端（chat / transcribe / tts）
│   │       ├── voice.py     语音对话服务：方案B 已实现，方案A 预留，Mock
│   │       ├── prompts.py   场景 System Prompt 模板 + 报告 Prompt
│   │       ├── report.py    报告生成 + too_short / abandoned 边界规则
│   │       └── sessions.py  业务逻辑（与框架无关）
│   ├── scripts/check_gateway.py   网关连通性自检
│   └── tests/test_flow.py         全流程测试（Mock + 模拟网关）
└── frontend/                uni-app (Vue3)：H5 + 微信小程序
    └── src/
        ├── pages/           scenes(P1) scenario(P2) drill(P3) train(P4) report(P5) records(P6) + 首页/练习本/我的
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

- 首次启动自动建库（`backend/data/talktool.db`）并写入 21 个场景。重置场景：`python3 -m app.db --reseed`
- 接口文档：http://127.0.0.1:8000/docs
- `.env` 里 `GATEWAY_API_KEY` 留空 = **Mock 模式**：不调网关，可走通全部页面和报告（AI 用固定台词）
- 测试：`python3 -m tests.test_flow`

## 2. 启动前端

```bash
cd frontend
npm install
npm run dev:h5            # 浏览器打开 http://localhost:5173
npm run dev:mp-weixin     # 用微信开发者工具导入 frontend/dist/dev/mp-weixin
```

- **H5**：`/api` 和 `/media` 由 vite 代理到 `127.0.0.1:8000`。麦克风要求 HTTPS 或 localhost，电脑浏览器直接用 localhost 即可；手机上测要走 HTTPS 隧道（如 `cloudflared tunnel --url http://localhost:5173`）。
- **小程序**：新建 `frontend/.env`，写入 `VITE_API_BASE=http://你的电脑局域网IP:8000`。开发者工具里勾选“不校验合法域名”；真机/上线需要 HTTPS 域名，并在小程序后台配置隐私协议（麦克风）。
- 如果 `npm install` 报 `@dcloudio` 版本问题：执行 `npx @dcloudio/uvm@latest` 对齐版本，或用 `npx degit dcloudio/uni-preset-vue#vite` 生成官方模板后把 `src/` 拷进去。

## 3. 网关对接（AIapiMgr）

| 环节 | 接口 | capability |
|---|---|---|
| AI 对练回复 | `POST /api/ai/chat` | `fast-chat`（低延迟） |
| 训练报告 | `POST /api/ai/chat` | `quality-chat` |
| 语音识别 | `POST /api/ai/transcribe`（multipart，WAV 16k） | `speech` |
| 语音合成 | `POST /api/ai/tts`（mp3） | `tts` |

Key 只在后端 `.env`，前端拿不到。租户要在网关「租户配额 → 能力」里开通这 4 个能力；如果开了 IP 白名单，记得加上服务器出口 IP。音色在 `.env` 的 `TTS_VOICE` 里改。

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

## 6. MVP 未做

登录（目前用设备 ID 区分用户）、练习本（Tab 占位）、支付、分享、排行榜、场景管理后台（改 `seed_data.py` 后执行 `--reseed`）。
