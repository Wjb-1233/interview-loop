from types import SimpleNamespace
import pytest

from app.features.evaluations.fillers import count_fillers
from app.features.evaluations.objectives import filler_density
from app.features.evaluations.service import speech_statistics
from tests.support.factories import client, register


@pytest.mark.parametrize('text', ['名额、金额、余额、配额都需要核对。', '额度限制和额外成本需要说明。', '额定功率和额头都不是口头禅。'])
def test_normal_words_do_not_become_single_character_fillers(text):
    assert count_fillers(text, ['额', '嗯']) == {}
    assert filler_density(text) == 0


def test_standalone_fillers_are_still_counted_and_round_boundaries_preserved():
    rows = [SimpleNamespace(speaker='USER', content='嗯，先确认名额。'), SimpleNamespace(speaker='USER', content='额，再核对金额，嗯。')]
    stats = speech_statistics(rows)
    assert stats['fillerTotal'] == 3
    assert stats['topFillers'] == [{'word': '嗯', 'count': 2}, {'word': '额', 'count': 1}]


def test_existing_report_recomputes_lexical_statistics_without_changing_saved_scores(client):
    import asyncio
    from app.db.base import session_factory
    from app.db.models import Evaluation
    headers = register(client)
    prepared = client.post('/api/v1/training-sessions', headers=headers, json={'sceneId': 'scene-interview-03'}).json()['data']
    for answer in ['报名名额不足时拒绝请求，避免超卖。', '按实际金额核对余额和额度。']:
        client.post(f"/api/v1/training-sessions/{prepared['id']}/messages/complete", headers=headers, json={'content': answer})
    original = client.post(f"/api/v1/training-sessions/{prepared['id']}/finish?create_plan=false", headers=headers).json()['data']
    async def old_stats():
        async with session_factory() as db:
            saved = await db.get(Evaluation, original['id'])
            saved.speech_stats = {'fillerTotal': 4, 'topFillers': [{'word': '额', 'count': 4}], 'technicalChecks': []}
            await db.commit()
    asyncio.run(old_stats())
    report = client.get(f"/api/v1/evaluations/{prepared['id']}", headers=headers).json()['data']
    assert report['speechStats']['fillerTotal'] == 0 and report['speechStats']['topFillers'] == []
    assert report['overallScore'] == original['overallScore'] and report['scores'] == original['scores']
