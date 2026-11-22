import asyncio

import pytest
from sqlalchemy import select

from app.db.base import session_factory
from app.db.models import Evaluation, EvaluationEvidence, Message, TrainingSession
from app.infrastructure.llm import llm_gateway
from tests.support.growth import seed
from tests.support.factories import client, register


def report(client, headers, session_id):
    response = client.get(f'/api/v1/evaluations/{session_id}', headers=headers)
    assert response.status_code == 200, response.text
    return response.json()['data']


@pytest.mark.parametrize('record,missing', [
    ({'evidence_dimensions': []}, ['logic', 'relevance', 'correctness', 'concision']),
    ({'evidence_dimensions': ['logic']}, ['relevance', 'correctness', 'concision']),
    ({'quote': '用户没有说过的话'}, ['logic', 'relevance', 'correctness', 'concision']),
])
def test_insufficient_reports_are_reference_only_without_model_calls(client, monkeypatch, record, missing):
    headers = register(client)
    ids = seed(client, headers, [{'days': 1, 'score': 60}, {**record, 'score': 99}])
    async def forbidden(*args, **kwargs):
        raise AssertionError('Read-only requests must not call the model')
    monkeypatch.setattr(llm_gateway, 'complete_json', forbidden)
    data = report(client, headers, ids[-1])
    assert data['qualityStatus'] == 'INSUFFICIENT_EVIDENCE'
    assert data['missingEvidenceDimensions'] == missing
    assert data['overallScore'] == 99 and data['degraded'] is False
    assert data['eligibleForGrowth'] is False and data['previousScores'] is None
    dashboard = client.get('/api/v1/dashboard', headers=headers).json()['data']
    assert dashboard['formalEvaluationCount'] == 1
    assert dashboard['latestSessionId'] == ids[0]
    assert dashboard['recentAverage'] == 60
    assert dashboard['overview']['trainingCount'] == 2
    assert client.get(f'/api/v1/dashboard?anchor_session_id={ids[-1]}', headers=headers).status_code == 404
    share = client.post(f'/api/v1/share/training-sessions/{ids[-1]}', headers=headers).json()['data']['url']
    shared = client.get('/api/v1' + share).json()['data']
    assert shared['qualityStatus'] == 'INSUFFICIENT_EVIDENCE'
    printable = client.get('/api/v1' + share + '/report')
    assert printable.status_code == 200
    assert '评分依据不完整' in printable.text and '暂不计入成长统计' in printable.text
    assert '本报告由本地评分规则生成' not in printable.text


def test_previous_report_uses_training_time_instead_of_regrading_time(client):
    headers = register(client)
    ids = seed(client, headers, [
        {'days': 5, 'score': 40, 'graded_later_days': 20},
        {'days': 4, 'score': 60},
        {'days': 3, 'score': 99, 'delivery': {'rescoreRequired': True}},
        {'days': 2, 'score': 98, 'evidence_dimensions': []},
        {'days': 1, 'score': 80},
    ])
    assert report(client, headers, ids[0])['previousOverall'] is None
    assert report(client, headers, ids[1])['previousOverall'] == 40
    assert report(client, headers, ids[-1])['previousOverall'] == 60


@pytest.mark.parametrize('corrupt', ['round', 'speaker', 'empty_reason', 'wrong_session', 'case'])
def test_broken_evidence_links_are_rejected_by_report_and_dashboard(client, corrupt):
    headers = register(client)
    ids = seed(client, headers, [{}, {}])
    async def damage():
        async with session_factory() as db:
            evaluation = await db.scalar(select(Evaluation).where(Evaluation.session_id == ids[-1]))
            evidence = await db.scalar(select(EvaluationEvidence).where(EvaluationEvidence.evaluation_id == evaluation.id, EvaluationEvidence.dimension == 'logic'))
            question = await db.get(Message, evidence.question_message_id)
            if corrupt == 'round': question.round_no = 8
            elif corrupt == 'speaker': question.speaker = 'USER'
            elif corrupt == 'empty_reason': evidence.reason = '   '
            elif corrupt == 'wrong_session': question.session_id = ids[0]
            else:
                answer = await db.get(Message, evidence.answer_message_id)
                answer.content = 'Use Redis to verify.'
                evidence.quote = 'use Redis'
            await db.commit()
    asyncio.run(damage())
    assert report(client, headers, ids[-1])['eligibleForGrowth'] is False
    assert client.get('/api/v1/dashboard', headers=headers).json()['data']['formalEvaluationCount'] == 1


@pytest.mark.parametrize('channel', ['TEXT', 'VOICE', 'VIDEO'])
@pytest.mark.parametrize('speaker', ['AI', 'USER'])
def test_repeat_messages_use_same_canonical_evidence_in_python_and_sql(client, channel, speaker):
    headers = register(client)
    ids = seed(client, headers, [{'channel': channel}, {'channel': channel}])
    repeat_id = 'z' + ids[-1].replace('-', '')

    async def add_repeat(point_evidence_to_repeat=False):
        async with session_factory() as db:
            evaluation = await db.scalar(select(Evaluation).where(Evaluation.session_id == ids[-1]))
            row = await db.scalar(select(EvaluationEvidence).where(
                EvaluationEvidence.evaluation_id == evaluation.id, EvaluationEvidence.dimension == 'logic'))
            field = 'question_message_id' if speaker == 'AI' else 'answer_message_id'
            original = await db.get(Message, getattr(row, field))
            if not point_evidence_to_repeat:
                # Equal timestamps exercise the stable ID tie-breaker as well.
                db.add(Message(id=repeat_id, session_id=ids[-1], speaker=speaker,
                               round_no=original.round_no, content=original.content,
                               created_at=original.created_at))
            else:
                setattr(row, field, repeat_id)
            await db.commit()

    asyncio.run(add_repeat())
    assert report(client, headers, ids[-1])['eligibleForGrowth'] is True
    assert client.get('/api/v1/dashboard', headers=headers).json()['data']['formalEvaluationCount'] == 2
    asyncio.run(add_repeat(True))
    assert report(client, headers, ids[-1])['eligibleForGrowth'] is False
    assert client.get('/api/v1/dashboard', headers=headers).json()['data']['formalEvaluationCount'] == 1


def test_transcript_rescore_is_atomic_preserves_revisions_and_restores_statistics(client, monkeypatch):
    headers = register(client)
    original = '我通过监控验证结果，再检查一致性。'
    edited = '我先检查一致性，再通过压力测试验证接口延迟。'
    ids = seed(client, headers, [{'channel': 'VOICE', 'delivery': {'transcript': [{'roundNo': 1, 'text': original}]}}])
    session_id = ids[0]
    before = report(client, headers, session_id)
    for text in [edited + '初稿', edited]:
        assert client.patch(f'/api/v1/training-sessions/{session_id}/transcript/1', headers=headers, json={'text': text}).status_code == 200
    pending = report(client, headers, session_id)
    assert pending['qualityStatus'] == 'PENDING_RESCORE'
    assert not pending['eligibleForGrowth']
    dashboard = client.get('/api/v1/dashboard', headers=headers).json()['data']
    assert dashboard['formalEvaluationCount'] == 0 and dashboard['summary']['sampleCount'] == 0
    assert dashboard['summary']['reportSummary'] is None
    assert dashboard['overview']['trainingCount'] == 1
    async def unavailable(*args, **kwargs):
        raise RuntimeError('test outage')
    monkeypatch.setattr(llm_gateway, 'complete_json', unavailable)
    failed = client.post(f'/api/v1/evaluations/{session_id}?force=true', headers=headers)
    assert failed.status_code == 503
    retained = report(client, headers, session_id)
    assert retained['id'] == before['id'] and retained['overallScore'] == before['overallScore']
    assert retained['revision'] == 1 and retained['qualityStatus'] == 'PENDING_RESCORE'
    async def complete(*args, **kwargs):
        return {'scores': {key: 4 for key in ['logic', 'relevance', 'correctness', 'concision']}, 'summary': '重评后的结论。', 'suggestions': [], 'styleTags': [], 'evidence': [dict(dimension=key, roundNo=1, quote=edited, reason='原话说明了验证行动。', nextAction='补充验证的具体结果。') for key in ['logic', 'relevance', 'correctness', 'concision']]}
    monkeypatch.setattr(llm_gateway, 'complete_json', complete)
    other = register(client)
    assert client.post(f'/api/v1/evaluations/{session_id}?force=true', headers=other).status_code == 404
    success = client.post(f'/api/v1/evaluations/{session_id}?force=true', headers=headers)
    assert success.status_code == 201, success.text
    data = success.json()['data']
    assert data['id'] == before['id'] and data['revision'] == 2
    assert data['eligibleForGrowth'] and data['qualityStatus'] == 'VERIFIED'
    assert data['revisionHistory'][0]['evidence'][0]['answer'] == original
    assert data['revisionHistory'][0]['overallScore'] == before['overallScore']
    assert all(item['answer'] == edited for item in data['evidence'])
    exported = client.get('/api/v1/auth/me/export', headers=headers).json()['data']
    assert exported['sessions'][0]['evaluation']['revisionHistory'][0]['overallScore'] == before['overallScore']
    dashboard = client.get('/api/v1/dashboard', headers=headers).json()['data']
    assert dashboard['formalEvaluationCount'] == 1 and dashboard['overview']['trainingCount'] == 1
    assert dashboard['summary'] is not None
    # A duplicate request cannot regrade a now valid report or create another history entry/plan.
    monkeypatch.setattr(llm_gateway, 'complete_json', unavailable)
    again = client.post(f'/api/v1/evaluations/{session_id}?force=true', headers=headers).json()['data']
    assert again['revision'] == 2 and again['qualityStatus'] == 'VERIFIED'
    assert client.get('/api/v1/training-plans', headers=headers).json()['data'] == []


def test_insufficient_report_can_be_repaired_without_transcript_edit(client, monkeypatch):
    headers = register(client)
    session_id = seed(client, headers, [{'evidence_dimensions': []}])[0]
    async def complete(*args, **kwargs):
        return {'scores': {key: 3 for key in ['logic', 'relevance', 'correctness', 'concision']}, 'summary': '补齐证据。', 'suggestions': [], 'styleTags': [], 'evidence': [dict(dimension=key, roundNo=1, quote='我通过监控验证结果', reason='原话说明验证行动。', nextAction='补充验证结果。') for key in ['logic', 'relevance', 'correctness', 'concision']]}
    monkeypatch.setattr(llm_gateway, 'complete_json', complete)
    repaired = client.post(f'/api/v1/evaluations/{session_id}?force=true', headers=headers)
    assert repaired.status_code == 201, repaired.text
    assert repaired.json()['data']['eligibleForGrowth']
    assert repaired.json()['data']['revisionHistory'][0]['qualityStatus'] == 'INSUFFICIENT_EVIDENCE'
