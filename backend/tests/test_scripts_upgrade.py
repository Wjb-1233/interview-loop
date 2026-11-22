"""话术优化：维度映射、试听及收藏操作的测试。"""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.features.scripts.service import DIMENSION_GUIDANCE, normalize_dimension
from app.main import app


def test_dimension_guidance_covers_four_dimensions() -> None:
    assert set(DIMENSION_GUIDANCE) == {"内容与逻辑", "贴合问题", "信息完整", "表达干净"}


def test_legacy_dimension_names_map_to_current() -> None:
    assert normalize_dimension("感染力") == "信息完整"
    assert normalize_dimension("逻辑性") == "内容与逻辑"
    assert normalize_dimension("贴合问题") == "贴合问题"
    assert normalize_dimension(None) is None


def _auth(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": f"script-{uuid4().hex[:8]}@example.com", "password": "ScriptTest123", "displayName": "话术", "consent": True},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['data']['accessToken']}"}


def test_preview_returns_audio_url(monkeypatch) -> None:
    from app.features.scripts import router as script_router

    monkeypatch.setattr(script_router, "preview_speech", lambda text: "/media/tts/probe.wav")
    with TestClient(app) as client:
        headers = _auth(client)
        response = client.post("/api/v1/scripts/preview", headers=headers, json={"text": "这是要试听的一句话"})
        assert response.status_code == 200
        assert response.json()["data"]["url"] == "/media/tts/probe.wav"


def test_preview_rejects_empty_text() -> None:
    with TestClient(app) as client:
        headers = _auth(client)
        response = client.post("/api/v1/scripts/preview", headers=headers, json={"text": "  "})
        assert response.status_code == 404


def test_slow_preview_does_not_block_favorite_or_delete(monkeypatch) -> None:
    from app.features.scripts import router as script_router

    entered, release = Event(), Event()
    def slow_preview(text):
        entered.set()
        assert release.wait(5)
        return '/media/tts/probe.mp3'

    monkeypatch.setattr(script_router, 'preview_speech', slow_preview)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
        headers = _auth(client)
        generated = client.post('/api/v1/scripts/generate', headers=headers, json={'objective': '说明项目职责', 'originalText': '我负责接口设计。'}).json()['data']['versions']
        preview = pool.submit(client.post, '/api/v1/scripts/preview', headers=headers, json={'text': '并发试听'})
        assert entered.wait(3)
        def other_actions():
            favorite = client.post(f"/api/v1/scripts/{generated[0]['id']}/favorite", headers=headers)
            deleted = client.delete(f"/api/v1/scripts/{generated[1]['id']}", headers=headers)
            return favorite, deleted
        actions = pool.submit(other_actions)
        try:
            favorite, deleted = actions.result(timeout=1)
            assert favorite.status_code == 200 and favorite.json()['data']['favorite'] is True
            assert deleted.status_code == 204
        finally:
            release.set()
        assert preview.result(timeout=3).status_code == 200


@pytest.mark.parametrize('suffix', ['.mp3', '.wav'])
def test_preview_reuses_cached_audio(monkeypatch, tmp_path, suffix):
    from app.core.config import settings
    from app.features.scripts.service import preview_speech
    from app.infrastructure import narration

    monkeypatch.setattr(settings, 'tts_dir', str(tmp_path))
    text = '已经试听过的文字。'
    digest = hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]
    (tmp_path / f'{digest}{suffix}').write_bytes(b'existing-audio')
    def unexpected_synthesis(*args, **kwargs):
        pytest.fail('cached audio must not trigger synthesis again')
    monkeypatch.setattr(narration, 'synthesize_slide', unexpected_synthesis)
    assert preview_speech(text) == f'/media/tts/{digest}{suffix}'


def test_concurrent_previews_use_separate_workspaces(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.features.scripts.service import preview_speech
    from app.infrastructure import narration
    from threading import Barrier

    monkeypatch.setattr(settings, 'tts_dir', str(tmp_path))
    barrier = Barrier(2)
    workspaces = []
    def synthesize(text, workdir, index, **kwargs):
        assert kwargs.get('split_text') is False
        workspaces.append(workdir)
        audio = workdir / 'slide-0.mp3'
        audio.write_bytes(text.encode('utf-8'))
        barrier.wait(timeout=3)
        return audio, 1, 'test'
    monkeypatch.setattr(narration, 'synthesize_slide', synthesize)
    texts = ['第一个试听内容。', '第二个试听内容。']
    with ThreadPoolExecutor(max_workers=2) as pool:
        urls = list(pool.map(preview_speech, texts))
    assert len(set(workspaces)) == 2
    for text, url in zip(texts, urls):
        assert (tmp_path / url.rsplit('/', 1)[-1]).read_bytes() == text.encode('utf-8')


def test_preview_provider_failure_is_actionable(monkeypatch):
    from app.features.scripts import router as script_router
    def unavailable(text):
        raise RuntimeError('no narration audio produced')
    monkeypatch.setattr(script_router, 'preview_speech', unavailable)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post('/api/v1/scripts/preview', headers=_auth(client), json={'text': '试听'})
        assert response.status_code == 503
        assert '试听' in response.json()['detail']


def test_preview_timeout_returns_specific_error(monkeypatch):
    import time
    from app.features.scripts import router as script_router

    def slow_preview(text):
        time.sleep(0.1)
        return '/media/tts/late.mp3'
    monkeypatch.setattr(script_router, 'PREVIEW_TIMEOUT_SECONDS', 0.02)
    monkeypatch.setattr(script_router, 'preview_speech', slow_preview)
    with TestClient(app) as client:
        response = client.post('/api/v1/scripts/preview', headers=_auth(client), json={'text': '试听'})
        assert response.status_code == 504
        assert response.json()['title'] == 'PREVIEW_TIMEOUT'
        assert '试听' in response.json()['detail']
