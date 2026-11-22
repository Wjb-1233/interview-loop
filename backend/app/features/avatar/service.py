"""Simli 会话令牌：服务端持有 API Key，浏览器只拿 5 分钟有效的 session_token。

接口约定（docs.simli.com/api-reference/compose-session-token）：
POST https://api.simli.ai/compose/token，请求头 x-simli-api-key，请求体 {faceId, ...}，
成功返回 {session_token, warnings?}；403 = 脸不属于本账号，422 = 参数非法，400 = 数据非法。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import AppError

logger = logging.getLogger(__name__)

SIMLI_TOKEN_URL = "https://api.simli.ai/compose/token"
TOKEN_TIMEOUT_SECONDS = 10.0
SESSION_MAX_SECONDS = 600
SESSION_IDLE_SECONDS = 180


def _proxy_url() -> str | None:
    """显式读取代理，绕开 httpx 解析 NO_PROXY（本机 NO_PROXY 含 [::1] 会让 httpx 抛 normalize_port）。"""
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = (os.environ.get(name) or "").strip()
        if value.startswith(("http://", "https://")):
            return value
    return None


def _client() -> httpx.AsyncClient:
    proxy = _proxy_url()
    # trust_env=False：不让 httpx 再去解析 HTTP(S)_PROXY / NO_PROXY 环境变量
    if proxy:
        return httpx.AsyncClient(timeout=TOKEN_TIMEOUT_SECONDS, trust_env=False, proxy=proxy)
    return httpx.AsyncClient(timeout=TOKEN_TIMEOUT_SECONDS, trust_env=False)


def configured() -> bool:
    return bool(settings.simli_api_key.strip())


async def create_session_token() -> dict[str, Any]:
    """换一张短时令牌；密钥缺失返回 503，上游异常统一 502，前端据此回退本地形象。"""

    api_key = settings.simli_api_key.strip()
    if not api_key:
        raise AppError(503, "SIMLI_NOT_CONFIGURED", "在线数字人未配置，已使用本地虚拟形象")

    payload = {
        "faceId": settings.simli_face_id,
        "apiVersion": "v2",
        "handleSilence": True,
        "maxSessionLength": SESSION_MAX_SECONDS,
        "maxIdleTime": SESSION_IDLE_SECONDS,
        "audioInputFormat": "pcm16",
    }
    try:
        async with _client() as client:
            response = await client.post(
                SIMLI_TOKEN_URL,
                json=payload,
                headers={"x-simli-api-key": api_key},
            )
    except httpx.HTTPError as exc:
        logger.warning("simli.token_request_failed error_type=%s", type(exc).__name__)
        raise AppError(502, "SIMLI_UNAVAILABLE", "在线数字人暂时不可用，已使用本地虚拟形象") from exc

    if response.status_code != 200:
        logger.warning("simli.token_rejected status_code=%s", response.status_code)
        raise AppError(502, "SIMLI_UNAVAILABLE", "在线数字人暂时不可用，已使用本地虚拟形象")

    try:
        body = response.json()
    except ValueError as exc:
        logger.warning("simli.token_bad_json")
        raise AppError(502, "SIMLI_UNAVAILABLE", "在线数字人暂时不可用，已使用本地虚拟形象") from exc

    token = body.get("session_token") if isinstance(body, dict) else None
    if not token:
        logger.warning("simli.token_missing")
        raise AppError(502, "SIMLI_UNAVAILABLE", "在线数字人暂时不可用，已使用本地虚拟形象")

    return {
        "sessionToken": token,
        "faceId": settings.simli_face_id,
        "maxSessionLength": SESSION_MAX_SECONDS,
        "warnings": body.get("warnings") or [],
    }
