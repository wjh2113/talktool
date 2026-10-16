# AIapiMgr 第三方应用接入指南

> 面向业务系统开发人员：如何通过本 LLM 网关调用大模型。  
> 版本日期：2026-09-29

---

## 1. 一句话说明

**业务应用只调用本网关，不直连 SiliconFlow / CherryIN / 官方大模型。**

- 鉴权：租户 **API Key**（不是管理员密码）
- 选模型：传逻辑能力名 `capability`（如 `fast-chat`），**不要传上游模型 ID**
- 计费：成功后按 Token × 权重扣 **积分**

```
业务应用 ──Bearer API Key──► AIapiMgr 网关 ──内部密钥──► 上游供应商
                              │
                              ├─ 选路由 / 主备切换
                              ├─ 扣积分
                              └─ 审计日志
```

---

## 2. 接入前准备（管理员 + 业务方）

| 步骤 | 谁做 | 做什么 |
|------|------|--------|
| 1 | 管理员 | 管理台配置供应商 Key，启用路由 |
| 2 | 管理员 | 确认能力已启用：`fast-chat` / `quality-chat` / `vision` / `speech` / `pronunciation` 等 |
| 3 | 管理员 | **租户配额** → 新建租户 → 充值积分 → **复制 API Key（只显示一次）** |
| 4 | 业务方 | 把 Key 放进**服务端**环境变量，不要进前端 / Git |
| 5 | 业务方 | 配置网关 Base URL，按本文调用接口 |

### 本地演示地址

| 项 | 值 |
|----|-----|
| 网关 Base URL | `http://127.0.0.1:8001` |
| OpenAPI 文档 | http://127.0.0.1:8001/docs |
| 管理台 | http://127.0.0.1:5174 （管理员密码，仅运维用） |
| 演示 API Key | `aam_demo_key_for_local_testing_only_001` |
| 演示租户 | `tenant_demo` |

### 生产环境地址（HTTPS）

| 项 | 值 |
|----|-----|
| 网关 Base URL | `https://aiapimgrapi.aidigitcloud.cn` |
| 健康检查 | https://aiapimgrapi.aidigitcloud.cn/health |
| OpenAPI 文档 | https://aiapimgrapi.aidigitcloud.cn/docs |
| 管理台 | https://aiapimgr.aidigitcloud.cn/ |
| HTTP | 自动 301 跳转 HTTPS |

生产环境请使用各自业务租户的独立 API Key（在管理台「租户配额」创建）。

---

## 3. 认证（必须）

所有业务接口都必须带：

```http
Authorization: Bearer <租户 API Key>
Content-Type: application/json
```

说明：

- **必须有密钥**。缺 Key / Key 错误 → `401`
- 租户 Key ≠ 管理员 JWT；业务系统**不能**用管理台密码调 `/api/ai/*`
- 上游供应商 Key 只存在网关内（加密存储），业务侧永远拿不到
- Key 只放服务端（BFF / 微服务），**禁止**写进浏览器或 App 安装包

---

## 4. 接口清单

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/ai/chat` | 统一对话 / 图文理解（主接口） |
| `POST` | `/api/ai/transcribe` | 语音转写（multipart 或 base64，见 §8） |
| `POST` | `/api/ai/transcribe/json` | 语音转写（JSON base64） |
| `POST` | `/api/ai/pronounce` | 发音评测（capability=`pronunciation`） |
| `POST` | `/api/ai/appearance` | 出镜评测（capability=`appearance`） |
| `POST` | `/api/ai/embeddings` | 文本向量化（见 §9） |
| `POST` | `/api/ai/rerank` | RAG 重排序 |
| `POST` | `/api/ai/search` | 网页检索（见下文 web-search） |
| `POST` | `/api/ai/images` | 文生图（capability=`image-gen`） |
| `POST` | `/api/ai/tts` | 文本转语音（capability=`tts`） |
| `GET` | `/api/ai/capabilities` | 查询当前可用能力列表 |

在线调试：打开 http://127.0.0.1:8001/docs

---

## 5. 能力（capability）怎么选

| capability | 场景 | 输入形式 |
|------------|------|----------|
| `fast-chat` | 客服、摘要、分类、改写、低延迟闲聊 | 纯文本 messages |
| `quality-chat` | 复杂写作、代码、深度推理 | 纯文本 messages |
| `embedding` | RAG 向量化 | `POST /api/ai/embeddings`（见 §9） |
| `rerank` | RAG 重排序 | 按上游约定 |
| `web-search` | 网页检索，返回带 URL 的条目 | `POST /api/ai/search` |
| `vision` | 图片理解、OCR、看图问答 | 多模态 messages（见 §7） |
| `speech` | 语音转写 ASR | `POST /api/ai/transcribe`（见 §8） |
| `pronunciation` | 发音评测（对照稿子打分，不走 quality-chat；zh/en/ja） | `POST /api/ai/pronounce` |
| `appearance` | 出镜评测（网关抽帧后走 vision；zh/en/ja） | `POST /api/ai/appearance` |
| `image-gen` | 文生图 | `POST /api/ai/images`（见下文） |
| `tts` | 文本转语音（SiliconFlow CosyVoice2 主 / 百炼 cosyvoice-v3-flash 兜底，按 UTF-8 字节计费） | `POST /api/ai/tts`（见下文） |
| `batch` | 离线标签、批量清洗 | 纯文本 |

**不要**在请求里写 `gpt-4o`、`Qwen2.5-72B` 等上游模型名。换模型由管理员在「模型路由」改，业务代码不用发版。

---

## 6. 文本对话调用

### 6.1 请求

```http
POST /api/ai/chat
Authorization: Bearer <租户 API Key>
Content-Type: application/json
```

```json
{
  "tenantId": "tenant_demo",
  "capability": "fast-chat",
  "messages": [
    { "role": "system", "content": "你是企业助手，回答简洁。" },
    { "role": "user", "content": "用三句话介绍本周销售情况" }
  ],
  "dataClass": "internal",
  "maxCostCny": 0.03,
  "fallback": true,
  "stream": false,
  "userId": "emp_10086",
  "idempotencyKey": "order-summary-20260823-001"
}
```

### 6.2 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `capability` | 是 | 逻辑能力名，见上表 |
| `messages` | 是 | OpenAI 风格消息数组 `[{role, content}]` |
| `tenantId` | 否 | 租户编码，便于审计；鉴权以 API Key 为准 |
| `dataClass` | 否 | 数据级别：`public` / `internal` / `confidential` 等，默认 `internal` |
| `maxCostCny` | 否 | 单次成本上限（元） |
| `fallback` | 否 | 是否允许主备切换，默认 `true` |
| `stream` | 否 | 是否流式，默认 `false` |
| `userId` | 否 | 业务用户 ID（入库会哈希） |
| `idempotencyKey` | 否 | 幂等键；同一租户同一 key 的成功响应会回放，不重复扣积分 |
| `temperature` / `max_tokens` | 否 | 透传上游的生成参数 |

### 6.3 cURL

```bash
curl http://127.0.0.1:8001/api/ai/chat \
  -H "Authorization: Bearer aam_demo_key_for_local_testing_only_001" \
  -H "Content-Type: application/json" \
  -d '{
    "tenantId": "tenant_demo",
    "capability": "fast-chat",
    "messages": [{"role": "user", "content": "你好"}],
    "dataClass": "internal",
    "fallback": true,
    "stream": false
  }'
```

### 6.4 成功响应（示意）

响应体兼容 OpenAI `chat.completion`，并带 `gateway` 扩展：

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "model": "Qwen/Qwen2.5-7B-Instruct",
  "choices": [
    {
      "index": 0,
      "message": { "role": "assistant", "content": "你好，我是……" },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 8,
    "total_tokens": 20
  },
  "gateway": {
    "requestId": "req_xxx",
    "capability": "fast-chat",
    "provider": "siliconflow",
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "fallback": false,
    "points": 0.02,
    "pointsBalance": 99999.98,
    "costCny": 0.000014,
    "latencyMs": 320
  }
}
```

### 6.5 响应头（建议业务侧落库）

| Header | 含义 |
|--------|------|
| `X-Request-Id` | 请求 ID |
| `X-Provider-Used` | 实际供应商 |
| `X-Capability` | 能力名 |
| `X-Fallback` | 是否发生降级 |
| `X-Points-Charged` | 本次扣除积分 |
| `X-Points-Balance` | 扣后余额 |

---

## 7. 图片（vision）调用

使用能力 **`vision`**，`content` 用多模态数组（OpenAI 兼容）：

```json
{
  "capability": "vision",
  "dataClass": "internal",
  "fallback": true,
  "messages": [
    {
      "role": "user",
      "content": [
        { "type": "text", "text": "请识别图中的发票金额和日期" },
        {
          "type": "image_url",
          "image_url": {
            "url": "data:image/jpeg;base64,/9j/4AAQ..."
          }
        }
      ]
    }
  ]
}
```

也可用可访问的公网/内网图片 URL（取决于上游是否能拉到）：

```json
"image_url": { "url": "https://your-cdn.example.com/invoice.jpg" }
```

注意：

- 需管理员启用 vision 对应上游（如智谱 VL / 通义 VL）
- Base64 会放大请求体，建议业务侧把图压到最长边 1280～1600 再传
- 网关 `vision` 上游超时 60 秒；业务 HTTP 超时请 ≥ 70 秒
- 上游 429/502 时不要立刻重打，等 3～5 秒再试一次，或提示稍后再试
- vision 通常比纯文本更耗 Token / 积分

---

## 8. 语音转写（speech）

使用能力 **`speech`**，走网关 `POST /api/ai/transcribe`（上游一般为 OpenAI 兼容的 `/audio/transcriptions`）。`language` 建议传 `zh` / `en` / `ja`，与后面的发音、出镜评测一致。

| 方式 | 说明 |
|------|------|
| multipart 上传文件 | `POST /api/ai/transcribe`，字段 `file` |
| JSON base64 | `POST /api/ai/transcribe/json`，字段 `audioBase64` |
| 业务侧自建 ASR → chat | 仍可用；不经过网关 speech |

### 8.1 multipart

```bash
curl http://127.0.0.1:8001/api/ai/transcribe \
  -H "Authorization: Bearer aam_demo_key_for_local_testing_only_001" \
  -F "file=@./sample.wav" \
  -F "capability=speech" \
  -F "language=zh" \
  -F "dataClass=internal" \
  -F "fallback=true"
```

### 8.2 JSON（base64）

```http
POST /api/ai/transcribe/json
Authorization: Bearer <租户 API Key>
Content-Type: application/json
```

```json
{
  "capability": "speech",
  "filename": "hello.wav",
  "mimeType": "audio/wav",
  "audioBase64": "<base64…>",
  "language": "zh",
  "dataClass": "internal",
  "fallback": true,
  "idempotencyKey": "asr-meeting-20260823-001"
}
```

### 8.3 成功响应（示意）

```json
{
  "text": "转写后的文字",
  "language": "zh",
  "filename": "hello.wav",
  "usage": { "prompt_tokens": 200, "completion_tokens": 40, "total_tokens": 240 },
  "gateway": {
    "requestId": "req_xxx",
    "capability": "speech",
    "provider": "siliconflow",
    "model": "FunAudioLLM/SenseVoiceSmall",
    "points": 0.24,
    "pointsBalance": 99999.76
  }
}
```

注意：

- 需管理员启用 speech 对应上游（如 SiliconFlow SenseVoice），并配置通道 Key
- 单文件上限约 **25MB**；上游可能另有时长限制
- ASR 若无 token 用量，网关会按音频体积估算并扣积分
- 转写后再对话：把 `text` 作为 user message 调 `fast-chat` / `quality-chat`

---

## 发音评测（pronunciation）

`speech` 只转写。发音打分走独立能力 `pronunciation`，**不走 quality-chat**。对照当时要念的稿子（`text`）评分，不要拿转写结果当稿子。

```http
POST /api/ai/pronounce
Authorization: Bearer <租户 API Key>
Content-Type: multipart/form-data
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `file` | 是 | 这一遍口播录音，格式与转写相同 |
| `text` | 是 | 当时要念的稿子，用来对读音 |
| `capability` | 是 | 固定 `pronunciation` |
| `language` | 是 | `zh` / `en` / `ja`（也认 zh-CN、en-US、ja-JP） |
| `fallback` | 否 | `true` 时主供应商失败再换备供应商 |
| `dataClass` | 否 | 默认 `internal` |
| `userId` | 否 | 记到用量上 |
| `tenantId` | 否 | 便于审计；鉴权以 API Key 为准 |

`text` 为空、超过 8000 字，或音频超过转写体积上限（25MB），直接 **400**，不会截断后假装评完。`language` 支持 `zh`、`en`、`ja`。转写与打分都按这个语种走；SenseVoice 主通道支持这三种，英文/日语时通义 Paraformer 兜底可能不准。

```bash
curl https://aiapimgrapi.aidigitcloud.cn/api/ai/pronounce \
  -H "Authorization: Bearer <租户 API Key>" \
  -F "file=@take.webm" \
  -F "text=今天天气很好。" \
  -F "capability=pronunciation" \
  -F "language=zh" \
  -F "fallback=true" \
  -F "dataClass=internal"
```

成功响应示意：

```json
{
  "score": 82,
  "accuracy": 0.82,
  "language": "zh",
  "text": "今天天气很好。",
  "transcript": "今天天气很好",
  "issues": [{ "quote": "…", "note": "这一句没有念准或漏了" }],
  "note": "大体对准稿子，有少量偏差",
  "gateway": {
    "requestId": "req_xxx",
    "capability": "pronunciation",
    "provider": "siliconflow",
    "fallback": false
  }
}
```

`score` 为 0–100。IP Studio 总评里的「发音」只采用这个分数。若租户开了能力白名单，需勾选 `pronunciation`（启动时会给已有 `speech` 白名单的租户、以及租户 `IP` 自动补上）。

IP Studio 不需要新密钥，沿用网关 Key，录音走 `/api/ai/pronounce`。点「语音测评」时按稿子自动判 `zh` / `en` / `ja`。

---

## 出镜评测（appearance）

调用方**不用抽帧**。上传这一遍口播视频，网关确认有画面、用 ffmpeg 抽 4 帧 JPEG（约 12% / 38% / 62% / 86%，最长边 480），再交给现有 **vision**（智谱 GLM-5v）。提示词固定在网关里：只评看镜头、表情、手势；不评读音、不评稿子。`note` 按 `language` 用中文、英文或日语写。画面里没有人时 `score` 为 `null`。只有声音、没有画面时 **400**，不要编一个出镜分。

```http
POST /api/ai/appearance
Authorization: Bearer <租户 API Key>
Content-Type: multipart/form-data
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `file` | 是 | 这一遍口播视频，格式与现在上传的 mp4 / webm 相同 |
| `text` | 是 | 当时口播提示里和出镜有关的句子：表情、动作、看镜头。不是让模型重写稿子 |
| `capability` | 是 | 固定 `appearance` |
| `language` | 否 | `zh` / `en` / `ja`（默认 `zh`，也认 zh-CN、en-US、ja-JP） |
| `fallback` | 否 | 默认 `true` |
| `dataClass` | 否 | 默认 `internal` |
| `userId` | 否 | 记到用量上 |

```bash
curl https://aiapimgrapi.aidigitcloud.cn/api/ai/appearance \
  -H "Authorization: Bearer <租户 API Key>" \
  -F "file=@take.webm" \
  -F "text=看镜头；表情轻松；手势不要过大" \
  -F "capability=appearance" \
  -F "language=zh" \
  -F "fallback=true" \
  -F "dataClass=internal"
```

英文口播把 `language` 换成 `en`，日语换成 `ja`，`text` 用当时口播提示里对应语言的出镜句子。评语 `note` 会用该语言写。

成功响应示意：

```json
{
  "score": 81,
  "note": "看镜头比较稳，手势略满",
  "language": "zh",
  "text": "看镜头；表情轻松；手势不要过大",
  "frames": 4,
  "filename": "take.webm",
  "usage": {
    "prompt_tokens": 2000,
    "completion_tokens": 40,
    "total_tokens": 2040
  },
  "gateway": {
    "requestId": "req_xxx",
    "capability": "appearance",
    "provider": "official-zhipu",
    "fallback": false
  }
}
```

`score` 为 0–100 或 `null`（画面里没有人）。按 vision 路由扣积分，记在能力 `appearance` 上。纯音频 **400**，文案随 `language`：中文「这是声音、没有画面，不要编一个出镜分」。若租户开了能力白名单，需勾选 `appearance`（启动时会给已有 `vision` 白名单的租户、以及租户 `IP` 自动补上）。

IP Studio 不需要新密钥。点「视频测评」时按稿子自动判 `zh` / `en` / `ja`，整段视频交给网关抽帧，浏览器不要截帧。

## 9. 向量（embedding）

使用能力 **`embedding`**，走网关 `POST /api/ai/embeddings`（上游一般为 OpenAI 兼容的 `/embeddings`）。

### 9.1 请求

```http
POST /api/ai/embeddings
Authorization: Bearer <租户 API Key>
Content-Type: application/json
```

```json
{
  "capability": "embedding",
  "input": "要向量化的文本",
  "dimensions": 1024,
  "dataClass": "internal",
  "fallback": true,
  "idempotencyKey": "embed-doc-20260823-001"
}
```

`input` 也支持字符串数组（批量）。`dimensions` 可选：传了会**优先**选用模型目录里配置了相同维度的路由，并透传给上游；未传则使用路由对应模型的默认维度（若已配置）。

### 9.2 cURL

```bash
curl http://127.0.0.1:8001/api/ai/embeddings \
  -H "Authorization: Bearer aam_demo_key_for_local_testing_only_001" \
  -H "Content-Type: application/json" \
  -d '{
    "capability": "embedding",
    "input": ["第一段文本", "第二段文本"],
    "dimensions": 1024,
    "dataClass": "internal",
    "fallback": true
  }'
```

### 9.3 成功响应（示意）

```json
{
  "object": "list",
  "model": "BAAI/bge-m3",
  "data": [
    { "object": "embedding", "index": 0, "embedding": [0.01, -0.02, "..."] }
  ],
  "usage": { "prompt_tokens": 12, "total_tokens": 12 },
  "gateway": {
    "requestId": "req_xxx",
    "capability": "embedding",
    "provider": "siliconflow",
    "model": "BAAI/bge-m3",
    "dimensions": 1024,
    "points": 0.006,
    "pointsBalance": 99999.99
  }
}
```

注意：

- 需在「模型路由」为 `embedding` 能力配置可用通道，并在「官网模型」目录为 embedding 模型填写**向量维度**（如 1024）
- 同一 `embedding` 能力下可挂多条路由；`dimensions` 用于在同一能力内自动优选匹配的路由，失败时再按主备 failover

---

## 网页检索（web-search）

业务**不要**直连博查 / Tavily / Serper 等检索厂商。带租户 Key 调用网关，把返回的 `results[].url/snippet` 自行写入后续 `quality-chat` 的 prompt。

```http
POST /api/ai/search
Authorization: Bearer <租户 API Key>
Content-Type: application/json
```

```json
{
  "capability": "web-search",
  "query": "某公司 2024 年 ESG 报告要点",
  "count": 8,
  "freshness": "oneYear",
  "dataClass": "internal",
  "fallback": true
}
```

```bash
curl https://aiapimgrapi.aidigitcloud.cn/api/ai/search \
  -H "Authorization: Bearer <租户 API Key>" \
  -H "Content-Type: application/json" \
  -d '{"capability":"web-search","query":"某公司 2024 ESG 报告","count":8,"fallback":true}'
```

成功响应示意：

```json
{
  "object": "search.results",
  "query": "某公司 2024 ESG 报告",
  "results": [
    {
      "title": "…",
      "url": "https://…",
      "snippet": "…",
      "siteName": "…",
      "publishedAt": "…"
    }
  ],
  "gateway": {
    "requestId": "req_xxx",
    "capability": "web-search",
    "provider": "bocha",
    "fallback": false,
    "points": 4
  }
}
```

计费：每次成功检索按 **1000 token 当量 × 路由权重 0.004 ≈ 4 积分**。失败不扣。默认主通道博查、备用 Tavily；管理员可在「供应商渠道」启用秘塔、Serper、Brave、Jina、Exa、Bing、SerpAPI、Google CSE（须在 Base URL 带 `?cx=`）作为后续备用。未配 Key 的通道不健康，网关自动跳过。若租户开了能力白名单，需勾选 `web-search`。

---

## 文生图（image-gen）

业务**不要**直连万相 / Kolors / OpenAI Images。带租户 Key 调用网关，只传 `capability=image-gen`，不要写上游模型名。换模型由管理员在「模型路由」改。`vision` 是看图/OCR，出图走本接口。

```http
POST /api/ai/images
Authorization: Bearer <租户 API Key>
Content-Type: application/json
```

```json
{
  "capability": "image-gen",
  "prompt": "竖屏封面：深夜书桌，暖色台灯，留白标题区",
  "n": 1,
  "size": "portrait",
  "negativePrompt": "文字, 水印, logo",
  "dataClass": "internal",
  "fallback": true
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `capability` | 否 | 默认 `image-gen` |
| `prompt` | 是 | 画面描述 |
| `n` | 否 | 张数，1–4，默认 1 |
| `size` | 否 | `portrait` / `landscape` / `square`，或 `1024x1024` |
| `ratio` | 否 | `size` 的别名 |
| `negativePrompt` | 否 | 负向提示（万相等支持时透传） |
| `fallback` | 否 | 是否主备切换，默认 `true` |

```bash
curl https://aiapimgrapi.aidigitcloud.cn/api/ai/images \
  -H "Authorization: Bearer <租户 API Key>" \
  -H "Content-Type: application/json" \
  -d '{"capability":"image-gen","prompt":"竖屏封面：深夜书桌，暖色台灯","size":"portrait","fallback":true}'
```

成功响应兼容 OpenAI `images.generations`，并带 `gateway` 扩展：

```json
{
  "created": 0,
  "data": [
    { "url": "https://…" }
  ],
  "gateway": {
    "requestId": "req_xxx",
    "capability": "image-gen",
    "provider": "siliconflow",
    "model": "Kwai-Kolors/Kolors",
    "fallback": false,
    "points": 10
  }
}
```

`data[]` 也可能是 `{ "b64_json": "…" }`。计费按张：每张按 **1000 token 当量 × 路由权重** 扣积分（Kolors 默认约 10 积分）。失败不扣。默认路由：SiliconFlow Kolors 主，通义万相 `wan2.2-t2i-flash` 官网兜底。若租户开了能力白名单，需勾选 `image-gen`。

IP Studio 只配网关，不要写万相 / SiliconFlow 上游 Key：

```
IMAGE_PROVIDER=gateway
LLM_GATEWAY_URL=https://aiapimgrapi.aidigitcloud.cn
LLM_GATEWAY_API_KEY=<租户 Key>
LLM_TENANT_ID=IP
LLM_CAPABILITY_IMAGE=image-gen
```

## 文本转语音（tts）

业务**不要**直连 SiliconFlow CosyVoice。带租户 Key 调用网关，只传 `capability=tts`，不要写上游模型名。换模型 / 换音色由管理员在「模型路由」改。默认路由 SiliconFlow `FunAudioLLM/CosyVoice2-0.5B`，按 UTF-8 输入字节计费。

```http
POST /api/ai/tts
Authorization: Bearer <租户 API Key>
Content-Type: application/json
```

```json
{
  "capability": "tts",
  "input": "今天天气真好，我们一起去公园吧。",
  "voice": "FunAudioLLM/CosyVoice2-0.5B:alex",
  "responseFormat": "mp3",
  "speed": 1.0,
  "dataClass": "internal",
  "fallback": true
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `capability` | 否 | 默认 `tts` |
| `input` | 是 | 要合成的文本（≤ 500KB UTF-8） |
| `voice` | 否 | 音色预设，如 `FunAudioLLM/CosyVoice2-0.5B:alex`；可选 `alex/anna/bella/benjamin/charles/claire/david/diana`。省略由上游取默认 |
| `responseFormat` | 否 | `mp3` / `wav` / `pcm` / `opus`（默认 `mp3`，返回二进制音频）；填 `b64_json` 则返回 JSON，音频以 hex 编码放在 `audio` 字段，方便移动端 / serverless |
| `speed` | 否 | 语速 0.25–4.0，默认 1.0 |
| `gain` | 否 | 音量 dB，-10–10 |
| `fallback` | 否 | 是否主备切换，默认 `true` |

```bash
curl https://aiapimgrapi.aidigitcloud.cn/api/ai/tts \
  -H "Authorization: Bearer <租户 API Key>" \
  -H "Content-Type: application/json" \
  -d '{"capability":"tts","input":"今天天气真好","voice":"FunAudioLLM/CosyVoice2-0.5B:alex","responseFormat":"mp3"}' \
  --output speech.mp3
```

默认响应是**二进制音频**（`Content-Type: audio/mpeg`），网关元信息放在响应头：

```
X-Request-Id: req_xxx
X-Provider-Used: siliconflow
X-Capability: tts
X-Points-Charged: 1.2
X-Points-Balance: 9998.8
```

若 `responseFormat=b64_json`，返回 JSON：

```json
{
  "audio": "494433...（hex 编码音频字节）",
  "format": "mp3",
  "gateway": {
    "requestId": "req_xxx",
    "capability": "tts",
    "provider": "siliconflow",
    "model": "FunAudioLLM/CosyVoice2-0.5B",
    "fallback": false,
    "points": 1.2
  }
}
```

计费按 UTF-8 输入字节估算 token，乘路由权重扣积分（CosyVoice2 默认约 1 积分/百字量级）。失败不扣。默认路由：SiliconFlow `FunAudioLLM/CosyVoice2-0.5B` 主，阿里云百炼 `cosyvoice-v3-flash` 官网兜底（百炼 TTS 走原生 `/api/v1/services/audio/tts/SpeechSynthesizer`，非 OpenAI 兼容，网关已内置适配）。若租户开了能力白名单，需勾选 `tts`。

### 9.5 声纹识别（voiceprint）

声纹识别识别「这是谁在说话」，与 ASR（说了什么）、发音评测（说得准不准）不同。网关接的是**科大讯飞声纹识别**，支持 1:1 验证与 1:N 辨认。流程：先创建特征库 → 注册声纹 → 验证/辨认。

- 上游：科大讯飞 `https://api.xf-yun.com/v1/private/s1aa729d0`（HMAC-SHA256 签名鉴权）
- 音频：网关自动用 ffmpeg 转成 16kHz/16bit/单声道 WAV，base64 后 ≤4MB，建议 3–5 秒
- 供应商密钥：管理台「供应商渠道 → 科大讯飞」，API Key 字段填 JSON：`{"app_id":"...","api_key":"...","api_secret":"..."}`
- 计费：按次扣积分（注册 2000 / 验证 1000 / 辨认 1500 token 当量 × 路由权重 0.005 ≈ 10/5/7.5 积分）。特征库创建/删除免费。失败不扣。若租户开了能力白名单，需勾选 `voiceprint`。

#### 1) 创建特征库（必须先做一次）

```bash
curl http://127.0.0.1:8001/api/ai/voiceprint/group \
  -H "Authorization: Bearer <租户 API Key>" \
  -H "Content-Type: application/json" \
  -d '{
    "groupId": "my_company_voice",
    "groupName": "员工声纹库",
    "groupInfo": "2026 入库"
  }'
```

返回 `{"ok": true, "operation": "group", "groupId": "...", "msg": "success", "gateway": {...}}`。删除传 `"delete": true`。

#### 2) 注册声纹（enroll）

```bash
curl http://127.0.0.1:8001/api/ai/voiceprint/enroll \
  -H "Authorization: Bearer <租户 API Key>" \
  -F "file=@voice_sample.wav" \
  -F "groupId=my_company_voice" \
  -F "featureId=user_1001" \
  -F "featureInfo=张三 2026-10-02"
```

返回 `{"ok": true, "operation": "enroll", "featureId": "user_1001", "gateway": {...}}`。同一 `featureId` 可多次注册以增强模型。

#### 3) 1:1 验证（verify）— 是不是这个人

```bash
curl http://127.0.0.1:8001/api/ai/voiceprint/verify \
  -H "Authorization: Bearer <租户 API Key>" \
  -F "file=@check.wav" \
  -F "groupId=my_company_voice" \
  -F "featureId=user_1001"
```

返回 `{"ok": true, "operation": "verify", "score": 0.92, "featureId": "user_1001", "gateway": {...}}`。`score` 0–1，越接近 1 越像；业务侧自定阈值（如 ≥0.8 判通过）。

#### 4) 1:N 辨认（identify）— 是库里的哪个人

```bash
curl http://127.0.0.1:8001/api/ai/voiceprint/identify \
  -H "Authorization: Bearer <租户 API Key>" \
  -F "file=@check.wav" \
  -F "groupId=my_company_voice" \
  -F "topK=3"
```

返回 `{"ok": true, "operation": "identify", "scoreList": [{"score":0.88,"featureId":"user_1001"}, ...], "gateway": {...}}`。`topK` 最大 10，按相似度降序。

#### 5) 备用通道：阿里云 AnalyticDB 声纹检索（邀测，URL 模式）

`voiceprint` 能力默认走讯飞（上传音频 bytes）。网关同时接了**阿里云 AnalyticDB for MySQL 声纹检索**作为 fallback：当讯飞不可用、或调用方显式传 `audioUrl` 时走此通道。

- **产品状态**：邀测中，需在阿里云提交工单开通 AnalyticDB 实例的声纹检索功能
- **端点**：用户自己的 AnalyticDB 实例私有地址（如 `http://xxx.ads.rds.aliyuncs.com:8100`），管理台「供应商渠道 → 阿里云 AnalyticDB 声纹检索」填入 base_url 与 API Key（Bearer 鉴权）
- **音频**：所有接口只收 `audioUrl`（OSS / 公网可访问 URL），**不接受文件 bytes**；调用方需先把音频传到 OSS 再调网关
- **无 group 概念**：AnalyticDB 声纹库就是实例本身，用 `featureId` 当 speaker `name`；`/voiceprint/group` 端点对此通道无效，注册/验证/辨认直接用 `featureId`
- **1:1 验证**：网关用 `/voice/search` 限定 `names=[featureId]` 取 top1 similarity 实现
- **计费**：与讯飞同档（注册 2000 / 验证 1000 / 辨认 1500 token 当量 × 路由权重）。失败不扣

```bash
# 注册（传 audioUrl，不传 file）
curl http://127.0.0.1:8001/api/ai/voiceprint/enroll \
  -H "Authorization: Bearer <租户 API Key>" \
  -F "audioUrl=https://oss-bucket/audio/user_1001.wav" \
  -F "featureId=user_1001"

# 1:1 验证
curl http://127.0.0.1:8001/api/ai/voiceprint/verify \
  -H "Authorization: Bearer <租户 API Key>" \
  -F "audioUrl=https://oss-bucket/audio/check.wav" \
  -F "featureId=user_1001"

# 1:N 辨认（全库搜索，无需 groupId）
curl http://127.0.0.1:8001/api/ai/voiceprint/identify \
  -H "Authorization: Bearer <租户 API Key>" \
  -F "audioUrl=https://oss-bucket/audio/check.wav" \
  -F "topK=3"
```

> 路由策略：讯飞为 primary、AnalyticDB 为 fallback（priority 20）。调用方传 `file` 走讯飞、传 `audioUrl` 走 AnalyticDB；若某候选通道与输入不匹配（如 AnalyticDB 通道但只传了 file），网关会跳过该候选并尝试下一个。两个通道都失败才返回 502。

### 9.6 说话人分离（speaker-diarization，阿里云百炼）

**与声纹识别的区别**：说话人分离只区分「这段录音里有几个人、谁在说哪句」，返回匿名 `speaker_id`（0/1/2…），**不识别真实身份**。要认「是谁」用上面的声纹识别。适合会议录音转写、客服对话按说话人归档等场景。

- 上游：阿里云百炼 `paraformer-v2`（`diarization_enabled=true`），公共端点 `dashscope.aliyuncs.com`
- 流程：网关自动上传音频到百炼临时存储（OSS，48h）→ 提交异步转写任务 → 轮询 → 下载结果解析 `speaker_id`
- 延迟：异步任务，通常几秒到几十秒（网关内置轮询，业务侧同步等待即可）
- 计费：按次扣积分（3000 token 当量 × 路由权重 0.002 ≈ 6 积分/次）。失败不扣。若租户开了能力白名单，需勾选 `speaker-diarization`。

```bash
curl http://127.0.0.1:8001/api/ai/diarization \
  -H "Authorization: Bearer <租户 API Key>" \
  -F "file=@meeting.wav" \
  -F "language=zh"
```

返回示例：

```json
{
  "ok": true,
  "capability": "speaker-diarization",
  "taskId": "abc123",
  "speakers": 2,
  "speakerIds": ["0", "1"],
  "segments": [
    {"speaker_id": "0", "text": "你好，请问有什么可以帮您？", "begin_time": 0, "end_time": 2000},
    {"speaker_id": "1", "text": "我想咨询一下产品价格。", "begin_time": 2100, "end_time": 4000}
  ],
  "text": "你好，请问有什么可以帮您？我想咨询一下产品价格。",
  "gateway": {"requestId": "...", "points": 6, "pointsBalance": 99994, ...}
}
```

`segments` 按时间顺序，每段含 `speaker_id`（匿名编号）、`text`、`begin_time`/`end_time`（毫秒）。也支持 `audioBase64` 表单字段（JSON base64 上传）。

## 10. 查询可用能力

```bash
curl http://127.0.0.1:8001/api/ai/capabilities \
  -H "Authorization: Bearer <租户 API Key>"
```

返回示例：

```json
{
  "data": [
    {
      "name": "fast-chat",
      "description": "…",
      "maxLatencyMs": 5000,
      "maxCostCny": 0.03,
      "maxDataClass": "internal"
    }
  ]
}
```

---

## 11. 代码示例

### 11.1 Python（httpx）

```python
import os
import httpx

GATEWAY = os.environ["LLM_GATEWAY_URL"]      # http://127.0.0.1:8001
API_KEY = os.environ["LLM_GATEWAY_API_KEY"]  # 租户 Key

def chat(text: str, capability: str = "fast-chat") -> str:
    r = httpx.post(
        f"{GATEWAY}/api/ai/chat",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "capability": capability,
            "messages": [{"role": "user", "content": text}],
            "dataClass": "internal",
            "fallback": True,
            "stream": False,
        },
        timeout=60.0,
    )
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]


def generate_image(prompt: str, size: str = "portrait") -> dict:
    r = httpx.post(
        f"{GATEWAY}/api/ai/images",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={"capability": "image-gen", "prompt": prompt, "size": size, "fallback": True},
        timeout=180.0,
    )
    r.raise_for_status()
    return r.json()
```

### 11.2 Node.js / BFF

```javascript
async function chat(question) {
  const res = await fetch(`${process.env.LLM_GATEWAY_URL}/api/ai/chat`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.LLM_GATEWAY_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      capability: "quality-chat",
      messages: [
        { role: "system", content: "You are a helpful assistant." },
        { role: "user", content: question },
      ],
      fallback: true,
      stream: false,
    }),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return {
    answer: data.choices[0].message.content,
    points: data.gateway?.points,
  };
}

async function generateImage(prompt, size = "portrait") {
  const res = await fetch(`${process.env.LLM_GATEWAY_URL}/api/ai/images`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.LLM_GATEWAY_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ capability: "image-gen", prompt, size, fallback: true }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
```

### 11.3 Java（示意）

```java
// POST {baseUrl}/api/ai/chat
// Header: Authorization: Bearer {apiKey}
// Body JSON: capability, messages, dataClass, fallback, stream
```

---

## 12. 错误码

| HTTP | 含义 | 业务侧建议 |
|------|------|------------|
| `401` | 缺少或错误的 API Key | 检查 Bearer；确认租户未停用 |
| `402` | 积分不足 / 预算超限 | 提示运营充值；管理员在租户配额加积分 |
| `403` | `dataClass` 超出该能力允许级别，或来源 IP 不在租户 IP 白名单内 | 降低级别，或让管理员把业务出口 IP 加入白名单 |
| `404` | 未知 `capability` | 与 `GET /api/ai/capabilities` 核对名称 |
| `409` | 幂等键冲突（多为流式重放） | 换新 `idempotencyKey`，或改非流式 |
| `503` | 无健康路由 | 联系管理员检查供应商 Key / 路由 / 健康检查 |

---

## 13. 积分与对账

- 公式：`积分 = total_tokens × weight`（路由上可配权重）
- 调用前预检余额；成功后扣减
- 以响应里的 `gateway.points` / 头 `X-Points-Charged` 为准做业务对账
- 余额不足返回 **402**，不会白打上游

---

## 14. 安全红线

1. **每个业务系统单独租户、单独 API Key、单独积分池**
2. Key 只放服务端环境变量 / 密钥管理系统
3. 不要把上游 SiliconFlow / OpenAI Key 配进业务系统
4. 生产关闭演示 Key，修改默认管理员密码
5. 网关走内网或 HTTPS；按租户配 **IP 白名单**（管理台「租户配额 → IP」），仅放行业务出口 IP/CIDR
6. 按需在「租户配额 → 能力」收紧能力白名单，只开放业务真正用到的能力

---

## 15. 接入检查清单

- [ ] 已拿到本业务专属 API Key，并写入服务端环境变量  
- [ ] Base URL 指向网关（非上游厂商）  
- [ ] 请求使用 `capability`，未写死上游模型名  
- [ ] 已处理 `401` / `402` / `503`  
- [ ] 重要业务传入 `idempotencyKey`（订单号 / 工单号）  
- [ ] 已记录 `X-Request-Id` 与积分相关响应头  
- [ ] 图片理解使用 `vision` + 多模态 `content`；图先压缩，HTTP 超时 ≥ 70 秒；429/502 不要立刻重打  
- [ ] 文生图使用 `image-gen` + `/api/ai/images`，不要写上游模型名  
- [ ] 语音场景使用 `speech` + `/api/ai/transcribe`，或业务侧 ASR 后再调 chat  
- [ ] 文本转语音使用 `tts` + `/api/ai/tts`，音色放 `voice`，不要写上游模型名
- [ ] 发音评测使用 `pronunciation` + `/api/ai/pronounce`，稿子放 `text`，`language` 用 zh/en/ja，不要让 quality-chat 打发音分
- [ ] 出镜评测使用 `appearance` + `/api/ai/appearance`，上传视频由网关抽帧，`language` 用 zh/en/ja，不要让业务侧抽帧或让 quality-chat 打出镜分  
- [ ] 向量场景使用 `embedding` + `/api/ai/embeddings`，`dimensions` 与知识库索引一致  

---

## 16. 相关文档

| 文档 | 路径 |
|------|------|
| 管理台操作手册（含菜单顺序、截图） | `docs/LLM-Gateway-Operating-Manual.docx` |
| **API + 路由配置一体手册**（全文复制给 AI 工具） | `docs/AIapiMgr-API与路由配置一体手册.md` · `.docx` |
| 第三方业务接入详解 | `docs/第三方应用接入指南.md` · `.docx` |
| 在线 OpenAPI（本地） | http://127.0.0.1:8001/docs |
| 在线 OpenAPI（生产） | https://aiapimgrapi.aidigitcloud.cn/docs |
| 生产管理台 | https://aiapimgr.aidigitcloud.cn/ |
| 项目 README | 仓库根目录 `README.md` |

---

## 17. 管理端 API（路由与模型目录）

> 以下接口需管理员 JWT：`POST /admin/api/auth/login` 获取 `access_token`，请求头 `Authorization: Bearer <token>`。

### 17.1 常用接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/admin/api/providers/presets` | 供应商预设（含官网模型建议列表与权重） |
| `GET` | `/admin/api/official-models` | 官网模型目录（含 `flash_relative`、¥/M 估算） |
| `GET` | `/admin/api/catalog-models` | 模型目录 CRUD 列表；`?channel_kind=official` 仅官网 |
| `GET` | `/admin/api/capabilities` | 能力定义 + 已挂路由 |
| `GET` | `/admin/api/routes` | 全部路由 |
| `POST` | `/admin/api/routes` | 新增路由（官网或聚合通道；官网权重取自目录，聚合通道可按对方已开通型号估算） |
| `GET` | `/admin/api/providers/{id}/upstream-models` | 读取聚合通道 Key 在对方站点已开通的模型列表（不写入本网关目录） |
| `PATCH` | `/admin/api/routes/{id}` | 更新角色 / 优先级 / 启用状态 |
| `GET` | `/admin/api/tenants` | 租户列表 |
| `PATCH` | `/admin/api/tenants/{id}` | 更新租户（名称 / 状态 / 日预算 / `ip_allowlist`） |
| `PATCH` | `/admin/api/tenants/{id}/capabilities` | 设置租户可用能力白名单 |

### 17.1.1 租户 IP 白名单

每个租户可单独配 **IP 白名单**，限制该租户的 API Key 只能从指定来源 IP / 网段调用，防止 Key 泄漏后被滥用。

- 管理台：「租户配额」→ 某行「IP」按钮。每行一个 IP 或 CIDR，例如 `10.0.0.0/8`、`203.0.113.5`。
- 留空 = 不限制（默认）。
- 网关取 `X-Forwarded-For` 首段判断来源（nginx/反代场景），回退 `X-Real-IP`、再回退连接 peer。
- 不在白名单内的请求返回 `403`，错误体含被拒 IP。
- 配置示例（`PATCH /admin/api/tenants/{id}`，body `{"ip_allowlist": "10.0.0.0/8\n203.0.113.5"}`）。

### 17.2 路由角色（role）

| role | 含义 | 典型用法 |
|------|------|----------|
| `primary` | 主通道 | 聚合商（SiliconFlow / CherryIN）或低成本官网 |
| `fallback` | 备通道 | 主通道失败时切换 |
| `official_fallback` | 官网兜底 | 仅 `official-*` 供应商；需已配置 API Key |

同一 `capability` 可挂多条路由；网关按 `priority` 升序尝试，同角色内数字越小越优先。

### 17.3 ROUTE_PRESETS 同步格式

仓库内 `backend/app/db/seed.py` 的 `ROUTE_PRESETS` 为默认路由真相源。每条路由：

```json
{
  "provider": "official-deepseek",
  "model": "Deepseek-V4-Flash",
  "role": "official_fallback",
  "priority": 80
}
```

可选字段：`dimensions`（embedding 能力，如 `1024`）。

同步命令（容器内）：

```bash
python -m app.db.sync_routes
```

或宿主机脚本：`scripts/sync-route-presets.sh`

### 17.4 添加路由的前提

**官网模型**

1. 在「模型目录」为对应 `official-*` 填写 API Key 并启用  
2. 模型已在官网目录中存在（启动时由预设 + CherryIN/官网价目自动同步）  
3. 「模型路由 → 添加路由 → 官网模型」仅列出 **已配置 Key** 的官网型号  

**聚合通道（SiliconFlow / CherryIN / 302.AI 等）**

1. 在「模型中心 → 供应商渠道」填写该通道 Base URL 与 API Key 并启用  
2. 「模型路由 → 添加路由 → 聚合通道」从「供应商渠道」选择供应商即可。**型号以对方官网已开通为准**（如 CherryIN 在其站点开通），本网关不建聚合模型目录  
3. 上游模型 ID **可不填**（`upstream_model` 为 `*` / `auto` / 空）。调用时网关用该 Key 请求对方 `GET /models`，按能力自动选用已开通型号；只有读不到列表时才退回本地预设。需要钉死某个型号时再填写或粘贴  
4. 角色只能是 **主通道** 或 **备用**；官网兜底仍仅用于官网直连

---

## 18. 计费与官网价格来源

### 18.1 积分公式

```
积分 = total_tokens × weight
weight = flash_relative × 0.001
flash_relative ≈ 混合价(¥/百万 Token) ÷ 10
混合价 = 输入价×25% + 输出价×75%
```

展示换算：约 **1 积分 ≈ ¥0.01**；`flash_relative = 1.0` 时约 **¥10 / 百万 Token**（与 DeepSeek V4 Flash 同级基准）。

### 18.2 价格数据来源（优先级）

| 优先级 | 来源 | 文件 / 接口 |
|--------|------|-------------|
| 1 | **厂商官网价目** | `backend/app/data/official_prices.json`（含 `source` URL） |
| 2 | CherryIN 公开价目 | `backend/app/data/cherryin_pricing.json`（`scripts/sync_cherryin_pricing.py` 同步） |
| 3 | 手工估算 | 仅用于 CherryIN 未收录的腾讯 / 百度 / 火山等补充型号 |

**以官网为准**：`official_prices.json` 有记录的型号，目录权重与 CherryIN 脱钩，按官网人民币或美元价目重算。

### 18.3 管理台「¥/M」列

`¥/M ≈ flash_relative × 10`，为混合 Token 的估算展示价，便于与厂商价目对照；实际扣费仍以调用后 `usage.total_tokens × weight` 为准。

---

## 19. 用 AI 生成路由配置

将 **`docs/AIapiMgr-API与路由配置一体手册.md` 全文**复制到 Cursor / GitHub Copilot / Claude 等 AI 工具，在文档 §8 补充业务场景；AI 会输出 `ROUTE_PRESETS` 兼容 JSON，可直接写入 `seed.py` 或经管理台启用。

业务侧详细接入说明仍见本文 §1–§15；一体手册侧重 API 参考 + 路由配置任务。

---

*— 完 —*
