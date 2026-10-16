"""网关连通性自检（只用标准库，安装依赖前也能跑）。

在 backend 目录执行：python3 scripts/check_gateway.py
依次检查：/health → /api/ai/capabilities → fast-chat → tts → speech（用刚合成的音频回测识别）
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ENV = Path(__file__).resolve().parent.parent / ".env"
if ENV.exists():
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

BASE = os.getenv("GATEWAY_BASE_URL", "https://aiapimgrapi.aidigitcloud.cn").rstrip("/")
KEY = os.getenv("GATEWAY_API_KEY", "")
TENANT = os.getenv("GATEWAY_TENANT_ID", "")
if not KEY:
    sys.exit("未配置 GATEWAY_API_KEY（backend/.env）")


def call(path, body=None, raw=None, ctype="application/json", method="POST"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method=method if data else "GET")
    req.add_header("Authorization", f"Bearer {KEY}")
    if data:
        req.add_header("Content-Type", ctype)
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=75) as r:
            return r.status, r.read(), dict(r.headers), int((time.time() - t) * 1000)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers), int((time.time() - t) * 1000)


def show(name, status, ms, extra=""):
    print(f"{'✅' if status < 400 else '❌'} {name:<14} HTTP {status}  {ms}ms  {extra}")


s, b, h, ms = call("/health", method="GET")
show("health", s, ms, b[:80].decode(errors="ignore"))

s, b, h, ms = call("/api/ai/capabilities", method="GET")
caps = [x.get("name") for x in json.loads(b).get("data", [])] if s < 400 else []
show("capabilities", s, ms, ", ".join(caps) or b[:200].decode(errors="ignore"))
for need in ("fast-chat", "quality-chat", "speech", "tts"):
    if caps and need not in caps:
        print(f"   ⚠️  租户未开通能力 {need}，请让管理员在「租户配额 → 能力」勾选")

common = {"dataClass": "internal", "fallback": True, **({"tenantId": TENANT} if TENANT else {})}
s, b, h, ms = call("/api/ai/chat", {**common, "capability": os.getenv("LLM_CAPABILITY", "fast-chat"),
                                    "messages": [{"role": "user", "content": "用一句话打个招呼"}], "stream": False})
reply = json.loads(b)["choices"][0]["message"]["content"] if s < 400 else b[:200].decode(errors="ignore")
show("fast-chat", s, ms, reply)

s, audio, h, ms = call("/api/ai/tts", {**common, "capability": "tts", "input": "你好，我们开始今天的训练吧。",
                                       "voice": os.getenv("TTS_VOICE", "FunAudioLLM/CosyVoice2-0.5B:alex"),
                                       "responseFormat": "mp3"})
show("tts", s, ms, f"{len(audio)} bytes, {h.get('Content-Type')}" if s < 400 else audio[:200].decode(errors="ignore"))

if s < 400:
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in {"capability": "speech", "language": "zh", "dataClass": "internal", "fallback": "true"}.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="t.mp3"\r\n'
                 f'Content-Type: audio/mpeg\r\n\r\n'.encode() + audio + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    s, b, h, ms = call("/api/ai/transcribe", raw=b"".join(parts), ctype=f"multipart/form-data; boundary={boundary}")
    show("speech", s, ms, json.loads(b).get("text") if s < 400 else b[:200].decode(errors="ignore"))
