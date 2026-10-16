"""AIapiMgr 网关客户端（详见《AIapiMgr 第三方应用接入指南》）。

用到三个接口，鉴权统一 `Authorization: Bearer <租户 API Key>`：
  POST {base}/api/ai/chat         capability=fast-chat / quality-chat   对话 & 报告
  POST {base}/api/ai/transcribe   capability=speech（multipart file）   语音识别
  POST {base}/api/ai/tts          capability=tts（返回二进制 mp3）        语音合成
"""
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
               max_tokens: int = 400, user_id: str = None) -> str:
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
    async with _client() as c:
        resp = await c.post(f"{config.GATEWAY_BASE_URL}/api/ai/chat", json=payload, headers=_headers())
    _check(resp, "对话")
    data = resp.json()
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as e:
        raise GatewayError(f"对话返回格式异常: {json.dumps(data, ensure_ascii=False)[:300]}") from e


async def transcribe(audio: bytes, filename: str = "audio.wav", mime: str = "audio/wav") -> str:
    data = {**{k: str(v).lower() if isinstance(v, bool) else v for k, v in _common().items()},
            "capability": config.ASR_CAPABILITY}
    if config.ASR_LANGUAGE:
        data["language"] = config.ASR_LANGUAGE
    files = {"file": (filename, audio, mime)}
    async with _client() as c:
        resp = await c.post(f"{config.GATEWAY_BASE_URL}/api/ai/transcribe",
                            data=data, files=files, headers=_headers(json_body=False))
    _check(resp, "语音识别")
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


async def capabilities() -> list:
    async with _client() as c:
        resp = await c.get(f"{config.GATEWAY_BASE_URL}/api/ai/capabilities", headers=_headers())
    _check(resp, "查询能力")
    return [x.get("name") for x in resp.json().get("data", [])]


def extract_json(text: str) -> dict:
    """从 LLM 输出中尽量解析出 JSON 对象（兼容 ```json 包裹、前后有说明文字）。"""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except ValueError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise GatewayError("报告 JSON 解析失败")
