from pathlib import Path

import pytest
from starlette.requests import Request

from app.core.config import settings
from app.core.errors import AppError
from app.infrastructure.rate_limit import (
    RateLimiter,
    client_identifier,
    resolve_client_ip,
)


@pytest.mark.asyncio
async def test_memory_rate_limiter_rejects_after_limit() -> None:
    limiter = RateLimiter()
    await limiter.check("test-user", limit=2, window_seconds=60)
    await limiter.check("test-user", limit=2, window_seconds=60)

    with pytest.raises(AppError) as captured:
        await limiter.check("test-user", limit=2, window_seconds=60)

    assert captured.value.status_code == 429
    assert captured.value.headers is not None
    assert int(captured.value.headers["Retry-After"]) >= 1
    await limiter.close()


def _request(peer: str, xff: str | None) -> Request:
    headers = [] if xff is None else [(b"x-forwarded-for", xff.encode("latin-1"))]
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": (peer, 12345),
            "server": ("testserver", 80),
        }
    )


def test_forged_xff_is_ignored_when_no_proxy_is_trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_count", 0)
    # 客户端自带 XFF 只是普通请求头，限流键必须来自 TCP 对端
    assert client_identifier(_request("198.51.100.9", "1.2.3.4")) == "198.51.100.9"
    assert client_identifier(_request("198.51.100.9", "1.2.3.4, 5.6.7.8")) == "198.51.100.9"


def test_single_trusted_proxy_takes_rightmost_hop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_count", 1)
    # 最右一跳由自家代理追加，左侧 1.2.3.4 是客户端伪造的
    assert client_identifier(_request("10.0.0.5", "1.2.3.4, 203.0.113.7")) == "203.0.113.7"


def test_two_trusted_proxies_take_second_hop_from_right(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_count", 2)
    assert client_identifier(_request("10.0.0.5", "1.2.3.4, 203.0.113.7, 10.0.0.2")) == "203.0.113.7"


def test_resolve_client_ip_counts_hops_from_the_right() -> None:
    assert resolve_client_ip("1.2.3.4, 5.6.7.8", "198.51.100.9", 0) == "198.51.100.9"
    assert resolve_client_ip("1.2.3.4, 5.6.7.8", "198.51.100.9", 1) == "5.6.7.8"
    assert resolve_client_ip("1.2.3.4, 5.6.7.8, 9.10.11.12", "198.51.100.9", 2) == "5.6.7.8"
    assert resolve_client_ip("1.2.3.4, 5.6.7.8, 9.10.11.12, 13.14.15.16", "198.51.100.9", 3) == "5.6.7.8"


@pytest.mark.parametrize("xff", [None, "", "   ", ",,", "not-an-ip", "1.2.3.4", "1.2.3.4, , 5.6.7.8"])
def test_resolve_client_ip_falls_back_to_peer_on_empty_or_malformed(xff: str | None) -> None:
    assert resolve_client_ip(xff, "198.51.100.9", 2) == "198.51.100.9"


def test_resolve_client_ip_reports_unknown_without_peer() -> None:
    assert resolve_client_ip(None, None, 0) == "unknown"


# ── 部署层不变量：镜像不许让 uvicorn 自己解析代理头 ────────────────────────
# uvicorn 的 --proxy-headers 会把 request.client 换成 X-Forwarded-For 的最左值，
# 而最左值完全由客户端控制；一旦如此，resolve_client_ip 收到的 peer 已是伪造值，
# trusted_proxy_count 守卫再正确也救不回来（限流键可随 XFF 轮换而轮换）。

REPO_ROOT = Path(__file__).resolve().parents[2]


def _dockerfile_without_comments() -> str:
    text = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_dockerfile_keeps_uvicorn_proxy_header_parsing_off() -> None:
    instructions = _dockerfile_without_comments()
    assert "--proxy-headers" not in instructions
    assert "--forwarded-allow-ips" not in instructions
    # uvicorn 的 --proxy-headers 默认就是开着的（只信任 127.0.0.1/::1），必须显式关掉
    assert "--no-proxy-headers" in instructions


def test_prod_setup_declares_trusted_proxy_count() -> None:
    compose = (REPO_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    env_example = (REPO_ROOT / ".env.production.example").read_text(encoding="utf-8")
    # 一层 nginx 前面：跳数必须显式声明，否则生产会退化成按 nginx 地址限流
    assert "TRUSTED_PROXY_COUNT" in compose
    assert "TRUSTED_PROXY_COUNT" in env_example


def test_uvicorn_proxy_headers_would_defeat_the_hop_guard() -> None:
    """说明性用例：把「为什么约束必须落在 Dockerfile」写成可执行的对照。"""
    xff = "6.6.6.6, 203.0.113.7"
    # 现状：peer 是真实 nginx 地址（镜像不开 proxy-headers），取最右一跳；
    # 客户端在左侧轮换伪造条目不影响限流键，第 11 次登录才被 429 拦住。
    assert resolve_client_ip(xff, "10.0.0.5", 1) == "203.0.113.7"
    assert resolve_client_ip("6.6.6.7, 203.0.113.7", "10.0.0.5", 1) == "203.0.113.7"
    # 若恢复 --proxy-headers，peer 变成最左伪造值：限流键跟着客户端轮换，等于自选键。
    assert resolve_client_ip(xff, "6.6.6.6", 0) == "6.6.6.6"
    assert resolve_client_ip("6.6.6.7, 203.0.113.7", "6.6.6.7", 0) == "6.6.6.7"
