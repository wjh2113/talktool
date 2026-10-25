"""真实 ASGI 路由回归：鉴权、智囊流程及跨账号隔离。"""
import os
import sys
import tempfile
import time

os.environ.update(DATA_DIR=tempfile.mkdtemp(), GATEWAY_API_KEY="", MOCK_MODE="true",
                  ADMIN_USERNAME="qa_admin", ADMIN_PASSWORD="test-password")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.testclient import TestClient
from app.main import app


def main():
    with TestClient(app) as client:
        def call(method, path, data=None, expected=200):
            response = client.request(method, path, json=data)
            assert response.status_code == expected, (path, response.status_code, response.text)
            return response.json()

        call("GET", "/api/advisor/home", expected=401)
        login = call("POST", "/api/auth/login", {"username": "qa_admin", "password": "test-password"})
        admin_token = login["token"]
        client.headers["Authorization"] = "Bearer " + admin_token
        for path in ("/api/advisor/home", "/api/councils", "/api/strategies", "/api/memory",
                     "/api/admin/prompts", "/api/admin/councils", "/api/admin/advisor-stats"):
            assert call("GET", path) is not None
        result = call("POST", "/api/consults", {"text": "王总总在会上否定我的方案，我想争取下季度项目负责人"})
        cid = result["id"]
        queued = call("POST", "/api/advisor/jobs", {"request_key": "api-plan-request", "kind": "plan", "consult_id": cid}, expected=202)
        replay = call("POST", "/api/advisor/jobs", {"request_key": "api-plan-request", "kind": "plan", "consult_id": cid}, expected=202)
        assert queued["id"] == replay["id"]
        for _ in range(100):
            state = call("GET", "/api/advisor/jobs/" + queued["id"])
            if state["status"] in ("done", "failed"):
                break
            time.sleep(0.05)
        assert state["status"] == "done", state
        assert call("GET", "/api/consults/" + str(cid))["plan"]["version"] == 1

        result = call("GET", f"/api/consults/{cid}")
        assert result["status"] == "planned"
        assert result["plan"]["content"]["lines"]
        pid = result["plan"]["id"]
        action = result["plan"]["actions"][0]["id"]
        call("PUT", f"/api/plan-actions/{action}", {"done": True})
        call("PUT", f"/api/plans/{pid}/rating", {"rating": 1})
        result = call("POST", f"/api/consults/{cid}/messages", {"text": "如果他反驳我，帮我改一下", "kind": "ask"})
        assert result["plan"]["version"] == 2
        result = call("POST", f"/api/consults/{cid}/roundtable", {})
        assert any(m["kind"] == "roundtable" for m in result["messages"])
        drill = call("POST", f"/api/consults/{cid}/rehearse", {})
        assert drill["frameworks"] and drill["pitfalls"]
        advisor = call("POST", "/api/my-advisors", {"name": "前辈", "persona": "擅长项目管理和务实沟通的前辈"})
        item = call("POST", "/api/memory/profile", {"text": "我是一名项目经理"})
        invites = call("POST", "/api/admin/invites", {"count": 1})
        code = invites[0]["code"] if isinstance(invites, list) else invites["items"][0]["code"]
        other = call("POST", "/api/auth/register", {"invite_code": code, "username": "other_user", "password": "test-password"})
        client.headers["Authorization"] = "Bearer " + other["token"]
        call("GET", "/api/advisor/jobs/" + queued["id"], expected=404)
        call("GET", "/api/advisor/jobs/find?consult_id=" + str(cid), expected=404)
        for method, path, data in (
            ("GET", f"/api/consults/{cid}", None),
            ("POST", f"/api/consults/{cid}/plan", {}),
            ("POST", f"/api/consults/{cid}/rehearse", {}),
            ("PUT", f"/api/plan-actions/{action}", {"done": True}),
            ("PUT", f"/api/plans/{pid}/rating", {"rating": -1}),
            ("DELETE", f"/api/my-advisors/{advisor['code']}", None),
        ):
            call(method, path, data, expected=404)
        assert call("GET", "/api/consults") == []
        assert call("GET", "/api/memory")["profile"] == []
        call("GET", "/api/admin/prompts", expected=403)
        client.headers["Authorization"] = "Bearer " + admin_token
        call("DELETE", f"/api/consults/{cid}")
        call("GET", f"/api/consults/{cid}", expected=404)
    print("ALL API TESTS PASSED")


if __name__ == "__main__":
    main()
