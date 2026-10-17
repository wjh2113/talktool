"""AIapiMgr 网关客户端（详见《AIapiMgr 第三方应用接入指南》）。

用到三个接口，鉴权统一 `Authorization: Bearer <租户 API Key>`：
  POST {base}/api/ai/chat         capability=fast-chat / quality-chat   对话 & 报告
  POST {base}/api/ai/transcribe   capability=speech（multipart file）   语音识别
  POST {base}/api/ai/tts          capability=tts（返回二进制 mp3）        语音合成
"""
import asyncio
import hashlib
import json
import logging
import re

from .. import config

log = logging.getLogger("talktool.gateway")

ERROR_HINTS = {
    401: "网关 API Key 缺失或错误，请检查 backend/.env 的 GATEWAY_API_KEY",
    402: "网关积分不足，请联系管理员充值",
    403: "数据级别超限或本机出口 IP 不在租户白名单",
    404: "未知 capability，请用 /api/ai/capabilities 核对能力名",
    503: "网关暂无可用路由，请联系管理员检查供应商配置",
}


class GatewayError(RuntimeError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def _headers(json_body: bool = True) -> dict:
    h = {"Authorization": f"Bearer {config.GATEWAY_API_KEY}"}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def _common() -> dict:
    body = {"dataClass": config.GATEWAY_DATA_CLASS, "fallback": True}
    if config.GATEWAY_TENANT_ID:
        body["tenantId"] = config.GATEWAY_TENANT_ID
    return body


def _client():
    import httpx  # 延迟导入：Mock 模式下不需要
    return httpx.AsyncClient(timeout=config.GATEWAY_TIMEOUT)


RETRY_STATUS = (429, 502, 503, 504)
RETRY_WAIT_SEC = 3  # 网关建议：429/502 等 3~5 秒再试一次


def idem_key(*parts) -> str:
    """幂等键：同一租户同一 key 的成功响应会被网关回放，不重复扣积分。"""
    raw = "|".join(str(p) for p in parts)
    return "tt-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:32]


async def _post(url: str, what: str, idempotent: bool, **kw):
    """POST 一次；带幂等键的请求遇到网络错误或 429/5xx 时等几秒重试一次（重试不会重复扣费）。"""
    attempts = 2 if idempotent else 1
    for i in range(attempts):
        try:
            async with _client() as c:
                resp = await c.post(url, **kw)
        except Exception as e:  # noqa: BLE001  网络异常
            if i + 1 < attempts:
                log.warning("%s 网络异常，%ss 后重试：%s", what, RETRY_WAIT_SEC, e)
                await asyncio.sleep(RETRY_WAIT_SEC)
                continue
            raise GatewayError(f"{what}失败：网络异常 {e}") from e
        if resp.status_code in RETRY_STATUS and i + 1 < attempts:
            log.warning("%s HTTP %s，%ss 后重试", what, resp.status_code, RETRY_WAIT_SEC)
            await asyncio.sleep(RETRY_WAIT_SEC)
            continue
        _check(resp, what)
        return resp


def _check(resp, what: str):
    if resp.status_code >= 400:
        hint = ERROR_HINTS.get(resp.status_code, "")
        body = resp.text[:300]
        log.warning("%s 失败 HTTP %s req=%s %s", what, resp.status_code, resp.headers.get("X-Request-Id"), body)
        raise GatewayError(f"{what}失败（HTTP {resp.status_code}）{('：' + hint) if hint else ''} {body}",
                           status=resp.status_code)
    log.info("%s ok req=%s points=%s balance=%s", what, resp.headers.get("X-Request-Id"),
             resp.headers.get("X-Points-Charged"), resp.headers.get("X-Points-Balance"))


async def chat(messages: list, capability: str = None, temperature: float = None,
               max_tokens: int = 400, user_id: str = None, idempotency_key: str = None,
               max_cost: float = None) -> str:
    payload = {
        **_common(),
        "capability": capability or config.LLM_CAPABILITY,
        "messages": messages,
        "stream": False,
        "temperature": config.LLM_TEMPERATURE if temperature is None else temperature,
        "max_tokens": max_tokens,
    }
    if user_id:
        payload["userId"] = user_id
    if idempotency_key:
        payload["idempotencyKey"] = idempotency_key
    if max_cost:
        payload["maxCostCny"] = max_cost
    resp = await _post(f"{config.GATEWAY_BASE_URL}/api/ai/chat", "对话", bool(idempotency_key),
                       json=payload, headers=_headers())
    data = resp.json()
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as e:
        raise GatewayError(f"对话返回格式异常: {json.dumps(data, ensure_ascii=False)[:300]}") from e


async def transcribe(audio: bytes, filename: str = "audio.wav", mime: str = "audio/wav",
                     idempotency_key: str = None) -> str:
    data = {**{k: str(v).lower() if isinstance(v, bool) else v for k, v in _common().items()},
            "capability": config.ASR_CAPABILITY}
    if config.ASR_LANGUAGE:
        data["language"] = config.ASR_LANGUAGE
    if idempotency_key:
        data["idempotencyKey"] = idempotency_key
    files = {"file": (filename, audio, mime)}
    resp = await _post(f"{config.GATEWAY_BASE_URL}/api/ai/transcribe", "语音识别", bool(idempotency_key),
                       data=data, files=files, headers=_headers(json_body=False))
    try:
        return (resp.json().get("text") or "").strip()
    except ValueError:
        return resp.text.strip()


async def speech(text: str) -> bytes:
    payload = {
        **_common(),
        "capability": config.TTS_CAPABILITY,
        "input": text,
        "responseFormat": "mp3",
        "speed": config.TTS_SPEED,
    }
    if config.TTS_VOICE:
        payload["voice"] = config.TTS_VOICE
    async with _client() as c:
        resp = await c.post(f"{config.GATEWAY_BASE_URL}/api/ai/tts", json=payload, headers=_headers())
    _check(resp, "语音合成")
    ctype = resp.headers.get("Content-Type", "")
    if "json" in ctype:  # 兜底：网关返回 JSON（hex 编码音频）
        return bytes.fromhex(resp.json().get("audio", ""))
    return resp.content


async def pronounce(audio: bytes, text: str, filename: str = "audio.wav", mime: str = "audio/wav") -> dict:
    """发音评测：对照稿子 text 打分。返回 {score, accuracy, transcript, issues:[{quote,note}], note}"""
    data = {**{k: str(v).lower() if isinstance(v, bool) else v for k, v in _common().items()},
            "capability": config.PRONOUNCE_CAPABILITY, "text": text, "language": config.ASR_LANGUAGE or "zh"}
    files = {"file": (filename, audio, mime)}
    async with _client() as c:
        resp = await c.post(f"{config.GATEWAY_BASE_URL}/api/ai/pronounce",
                            data=data, files=files, headers=_headers(json_body=False))
    _check(resp, "发音评测")
    return resp.json()


async def capabilities() -> list:
    async with _client() as c:
        resp = await c.get(f"{config.GATEWAY_BASE_URL}/api/ai/capabilities", headers=_headers())
    _check(resp, "查询能力")
    return [x.get("name") for x in resp.json().get("data", [])]


def _json_candidates(text: str) -> list:
    """抽出可能的 JSON 片段：整段、去掉 markdown 围栏、第一个 { 到最后一个 }。"""
    text = (text or "").strip()
    if not text:
        return []
    out, seen = [], set()

    def add(s):
        s = (s or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)

    add(text)
    fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.M).strip()
    add(fenced)
    # 模型常在围栏前后加说明文字，再抠一次围栏内内容
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.I)
    if m:
        add(m.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        add(text[start:end + 1])
    if fenced is not text:
        start, end = fenced.find("{"), fenced.rfind("}")
        if start != -1 and end > start:
            add(fenced[start:end + 1])
    return out


def _json_variants(chunk: str) -> list:
    """对同一段 JSON 做常见修复：尾逗号、中英文弯引号。"""
    variants, seen = [], set()

    def add(s):
        if s and s not in seen:
            seen.add(s)
            variants.append(s)

    add(chunk)
    # 对象/数组末尾多余逗号：{"a":1,} / [1,2,]
    no_trail = re.sub(r",(\s*[}\]])", r"\1", chunk)
    add(no_trail)
    # 弯引号 → 直引号（模型偶尔把中文引号写进 JSON 键值外层）
    for base in (chunk, no_trail):
        add(base.replace("\u201c", '"').replace("\u201d", '"')
                .replace("\u2018", "'").replace("\u2019", "'")
                .replace("「", '"').replace("」", '"'))
    return variants


def extract_json(text: str) -> dict:
    """从 LLM 输出中尽量解析出 JSON 对象（兼容 markdown 围栏、前后说明、尾逗号等）。"""
    last_err = None
    for cand in _json_candidates(text):
        for variant in _json_variants(cand):
            try:
                obj = json.loads(variant)
            except ValueError as e:
                last_err = e
                continue
            if isinstance(obj, dict):
                return obj
    hint = f"：{last_err}" if last_err else ""
    raise GatewayError(f"报告 JSON 解析失败{hint}")
