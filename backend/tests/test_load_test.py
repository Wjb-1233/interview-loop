from scripts.load_test import AttemptResult, build_summary, parse_sse_data, percentile
import asyncio
import httpx
import pytest
from scripts.load_test import run_virtual_user, parse_metrics, resource_summary


def test_percentile_uses_linear_interpolation() -> None:
    assert percentile([100, 200, 300, 400], 0.50) == 250
    assert percentile([100, 200, 300, 400], 0.95) == 385
    assert percentile([], 0.95) is None


def test_summary_rejects_degraded_or_slow_runs() -> None:
    results = [
        AttemptResult(
            virtual_user=1,
            success=True,
            first_token_ms=3500,
            total_response_ms=4000,
            degraded=True,
        ),
        AttemptResult(
            virtual_user=2,
            success=True,
            first_token_ms=4000,
            total_response_ms=4500,
        ),
    ]

    summary = build_summary(
        results,
        wall_seconds=5,
        target_first_token_ms=3000,
        allow_degraded=False,
    )

    assert summary["successRate"] == 1
    assert summary["degradedResponses"] == 1
    assert summary["latencyMs"]["firstToken"]["p95"] == 3975
    assert summary["releaseGates"]["noUnexpectedDegradation"] is False
    assert summary["releaseGates"]["firstTokenP95WithinTarget"] is False
    assert summary["passed"] is False


def test_summary_allows_local_fallback_when_explicit() -> None:
    result = AttemptResult(
        virtual_user=1,
        success=True,
        first_token_ms=120,
        degraded=True,
    )
    summary = build_summary(
        [result],
        wall_seconds=0.2,
        target_first_token_ms=3000,
        allow_degraded=True,
    )
    assert summary["passed"] is True


def test_sse_payload_parser_is_defensive() -> None:
    assert parse_sse_data('data: {"degraded": true}') == {"degraded": True}
    assert parse_sse_data("data: not-json") == {}


@pytest.mark.parametrize('fail_stream', [False, True])
def test_load_test_discards_its_session_even_on_stream_error(fail_stream):
    deleted = []
    def respond(request):
        if request.url.path.endswith('/discard'):
            deleted.append(request.url.path)
            return httpx.Response(204)
        if request.url.path.endswith('/messages'):
            if fail_stream:
                return httpx.Response(503)
            return httpx.Response(200, text='event: token\ndata: {"content":"你好"}\n\nevent: done\ndata: {}\n\n')
        return httpx.Response(201, json={'data': {'id': 'temporary-only'}})
    async def run():
        async with httpx.AsyncClient(base_url='http://local/api/v1', transport=httpx.MockTransport(respond)) as client:
            event = asyncio.Event()
            event.set()
            return await run_virtual_user(1, start=event, client=client, token='test-token', scene_id='s', message='test')
    result = asyncio.run(run())
    assert result.success is not fail_stream and result.cleanup_success is True
    assert deleted == ['/api/v1/training-sessions/temporary-only/discard']


def test_cleanup_failure_is_a_release_failure_and_metrics_do_not_invent_cost():
    result = AttemptResult(virtual_user=1, success=True, first_token_ms=10, cleanup_attempted=True, cleanup_success=False)
    assert not build_summary([result], wall_seconds=1, target_first_token_ms=3000, allow_degraded=False)['passed']
    before = parse_metrics('process_resident_memory_bytes 100\nprocess_cpu_seconds_total 1\n')
    after = parse_metrics('process_resident_memory_bytes 200\nprocess_cpu_seconds_total 2\napp_events_total{event="llm_usage",outcome="unreported"} 5\n')
    report = resource_summary([before, after], 2)
    assert report['sampledRssPeakBytes'] == 200 and report['oneCoreCpuPercent'] == 50
    assert report['cost'] is None and report['modelCountersDelta']
