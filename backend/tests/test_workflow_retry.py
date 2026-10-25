"""结构化输出截断时重试，并确保重试不会命中原来的幂等缓存。"""
import asyncio
import os
import sys
import tempfile
from unittest.mock import patch

os.environ.update(DATA_DIR=tempfile.mkdtemp(), MOCK_MODE="true")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services import gateway, workflow


async def test_json_retry():
    meta = {"max_tokens": 500, "capability": "fast-chat", "temperature": 0.2, "version": 0, "output": "json"}
    calls = []

    async def chat(*args, **kwargs):
        calls.append(kwargs)
        return '{"council":' if len(calls) == 1 else '{"council":"upward"}'

    with patch.object(workflow.prompt_store, "render", return_value=([], meta)), patch.object(gateway, "chat", chat):
        data, _ = await workflow._call("intent", {}, "user", (1, "situation"))
    assert data["council"] == "upward"
    assert [c["max_tokens"] for c in calls] == [500, 1500]
    assert calls[0]["idempotency_key"] != calls[1]["idempotency_key"]
    assert calls[0]["max_cost"] == calls[1]["max_cost"]
    assert all(c["thinking"] is False for c in calls)

    calls.clear()

    async def invalid(*args, **kwargs):
        calls.append(kwargs)
        return '{"broken":'

    with patch.object(workflow.prompt_store, "render", return_value=([], meta)), patch.object(gateway, "chat", invalid):
        try:
            await workflow._call("intent", {}, "user", (2,))
        except gateway.GatewayError:
            pass
        else:
            raise AssertionError("连续两次无效 JSON 必须报错")
    assert len(calls) == 2

    calls.clear()

    async def unavailable(*args, **kwargs):
        calls.append(kwargs)
        raise gateway.GatewayError("网关不可用")

    with patch.object(workflow.prompt_store, "render", return_value=([], meta)), patch.object(gateway, "chat", unavailable):
        try:
            await workflow._call("intent", {}, "user", (3,))
        except gateway.GatewayError:
            pass
        else:
            raise AssertionError("网络错误必须传递给调用方")
    assert len(calls) == 1
    print("ALL WORKFLOW RETRY TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(test_json_retry())
