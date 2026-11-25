import httpx
import pytest

from app.core.config import Settings
from app.infrastructure.llm import LlmGateway


def llm_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "llm_api_key": "test-key",
        "llm_base_url": "https://llm.example.com",
        "llm_model": "test-model",
        "llm_healthcheck_timeout_seconds": 1,
        "llm_healthcheck_ttl_seconds": 300,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_llm_health_requires_configuration() -> None:
    gateway = LlmGateway(llm_settings(llm_api_key=""))
    assert await gateway.health_status() == "unconfigured"


@pytest.mark.asyncio
async def test_llm_health_success_is_cached() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "OK"}}]},
        )

    gateway = LlmGateway(llm_settings(), httpx.MockTransport(handler))
    assert await gateway.health_status() == "ok"
    assert await gateway.health_status() == "ok"
    assert calls == 1


@pytest.mark.asyncio
async def test_llm_health_reports_authentication_failure() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(401, json={"error": "invalid key"}))
    gateway = LlmGateway(llm_settings(), transport)
    assert await gateway.health_status() == "auth_error"


@pytest.mark.asyncio
async def test_llm_health_reports_unreachable_provider() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("provider unavailable", request=request)

    gateway = LlmGateway(llm_settings(), httpx.MockTransport(handler))
    assert await gateway.health_status() == "unreachable"


@pytest.mark.asyncio
async def test_json_usage_counts_only_provider_reported_tokens(monkeypatch):
    events = []
    monkeypatch.setattr('app.infrastructure.llm.incr_event', lambda *args: events.append(args))
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={
        'choices': [{'message': {'content': '{"ok":true}'}}],
        'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}))
    assert await LlmGateway(llm_settings(), transport).complete_json('system', 'user') == {'ok': True}
    assert ('llm_attempts', 'json') in events
    assert ('llm_tokens', 'input', 100) in events and ('llm_tokens', 'output', 20) in events


@pytest.mark.asyncio
@pytest.mark.parametrize('reported', [True, False])
async def test_stream_usage_handles_empty_choices_and_missing_usage(monkeypatch, reported):
    events = []
    monkeypatch.setattr('app.infrastructure.llm.incr_event', lambda *args: events.append(args))
    stream = 'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n'
    if reported:
        stream += 'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":2}}\n\n'
    stream += 'data: [DONE]\n\n'
    transport = httpx.MockTransport(lambda _: httpx.Response(200, text=stream))
    gateway = LlmGateway(llm_settings(), transport)
    assert [text async for text in gateway.stream_text('system', [])] == ['你好']
    assert ('llm_usage', 'reported' if reported else 'unreported') in events
    assert any(event[0] == 'llm_tokens' for event in events) is reported
