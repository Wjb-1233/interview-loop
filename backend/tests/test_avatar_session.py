"""在线数字人令牌接口：没有密钥就 503 让前端回退，上游失败 502，成功也绝不下发密钥。"""

from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from app.core.config import settings
from app.features.avatar import service
from app.main import app


def _auth(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"simli-{uuid4().hex[:8]}@example.com",
            "password": "GraduateDesign123!",
            "displayName": "数字人",
            "consent": True,
        },
    )
    return {"Authorization": f"Bearer {response.json()['data']['accessToken']}"}


def _patch_transport(monkeypatch, handler) -> None:
    """把 service 的 httpx.AsyncClient 换成 MockTransport：断言离线，且能看请求头。"""
    monkeypatch.setattr(
        service,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def test_simli_session_requires_configuration(monkeypatch) -> None:
    monkeypatch.setattr(settings, "simli_api_key", "")

    with TestClient(app, client=(f"simli-{uuid4().hex}", 50210)) as client:
        headers = _auth(client)
        response = client.get("/api/v1/avatar/simli-session", headers=headers)

    assert response.status_code == 503, response.text
    assert response.json()["title"] == "SIMLI_NOT_CONFIGURED"


def test_simli_session_requires_login() -> None:
    with TestClient(app, client=(f"simli-{uuid4().hex}", 50211)) as client:
        response = client.get("/api/v1/avatar/simli-session")

    assert response.status_code == 401, response.text


def test_simli_session_reports_upstream_failure(monkeypatch) -> None:
    monkeypatch.setattr(settings, "simli_api_key", "test-simli-key")
    _patch_transport(monkeypatch, lambda _request: httpx.Response(403, json={"detail": "FACE_NOT_ALLOWED"}))

    with TestClient(app, client=(f"simli-{uuid4().hex}", 50212)) as client:
        headers = _auth(client)
        response = client.get("/api/v1/avatar/simli-session", headers=headers)

    assert response.status_code == 502, response.text
    assert response.json()["title"] == "SIMLI_UNAVAILABLE"
    assert "数字人" in response.json()["detail"]


def test_simli_session_returns_token_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "simli_api_key", "test-simli-key")
    monkeypatch.setattr(settings, "simli_face_id", "14c60d62-6ebf-424d-b626-1f4f91c33b04")
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-simli-api-key", "")
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"session_token": "tok_123", "warnings": []})

    _patch_transport(monkeypatch, handler)

    with TestClient(app, client=(f"simli-{uuid4().hex}", 50213)) as client:
        headers = _auth(client)
        response = client.get("/api/v1/avatar/simli-session", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["sessionToken"] == "tok_123"
    assert body["faceId"] == "14c60d62-6ebf-424d-b626-1f4f91c33b04"
    # 密钥只出现在发往上游的请求头里，响应体任何位置都不许有
    assert "test-simli-key" not in response.text
    assert seen["url"] == service.SIMLI_TOKEN_URL
    assert seen["key"] == "test-simli-key"
    assert '"faceId"' in seen["body"]


def test_simli_session_reports_network_failure(monkeypatch) -> None:
    monkeypatch.setattr(settings, "simli_api_key", "test-simli-key")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("upstream down", request=request)

    _patch_transport(monkeypatch, handler)

    with TestClient(app, client=(f"simli-{uuid4().hex}", 50214)) as client:
        headers = _auth(client)
        response = client.get("/api/v1/avatar/simli-session", headers=headers)

    assert response.status_code == 502, response.text
    assert response.json()["title"] == "SIMLI_UNAVAILABLE"
