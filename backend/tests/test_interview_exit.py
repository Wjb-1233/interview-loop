import asyncio
import json

import pytest
from sqlalchemy import func, select

from app.db.base import session_factory
from app.db.models import Evaluation, Message, ResumeContext, TrainingSession
from app.features.training.service import discard_training_session
from app.infrastructure.llm import llm_gateway
from tests.support.factories import client, register

ANSWER = '我负责订单接口设计，通过缓存减少重复查询，再用监控验证延迟和一致性。'


def prepare(client, headers, channel='TEXT'):
    response = client.post('/api/v1/training-sessions/prepare', headers=headers, data={'sceneId': 'scene-interview-03', 'channel': channel})
    assert response.status_code == 201, response.text
    return response.json()['data']['id']


def answer(client, headers, session_id, channel, count):
    if channel == 'TEXT':
        for _ in range(count):
            result = client.post(f'/api/v1/training-sessions/{session_id}/messages/complete', headers=headers, json={'content': ANSWER})
            assert result.status_code == 200, result.text
    elif count:
        result = client.post('/api/v1/voice/sessions', headers=headers, data={'sceneId': 'scene-interview-03', 'channelHint': channel, 'preparedSessionId': session_id, 'turns': json.dumps([{'question': '请解释如何验证结果。', 'answer': ANSWER} for _ in range(count)])})
        assert result.status_code == 201, result.text


@pytest.mark.parametrize('channel', ['TEXT', 'VOICE', 'VIDEO'])
@pytest.mark.parametrize('rounds', [0, 1, 3])
def test_direct_exit_removes_attempt_messages_context_and_statistics(client, monkeypatch, channel, rounds):
    headers = register(client)
    session_id = prepare(client, headers, channel)
    answer(client, headers, session_id, channel, rounds)
    async def add_context():
        async with session_factory() as db:
            db.add(ResumeContext(session_id=session_id, filename='resume.txt', content='测试简历内容。'))
            await db.commit()
    asyncio.run(add_context())
    async def forbidden(*args, **kwargs):
        raise AssertionError('Exiting must not grade or generate a plan')
    monkeypatch.setattr(llm_gateway, 'complete_json', forbidden)
    assert client.post(f'/api/v1/training-sessions/{session_id}/discard', headers=headers).status_code == 204
    assert client.post(f'/api/v1/training-sessions/{session_id}/discard', headers=headers).status_code == 204
    assert client.get(f'/api/v1/training-sessions/{session_id}', headers=headers).status_code == 404
    history = client.get('/api/v1/training-sessions', headers=headers).json()['data']
    assert not any(row['id'] == session_id for row in history)
    assert client.get('/api/v1/training-plans', headers=headers).json()['data'] == []
    assert client.get('/api/v1/dashboard', headers=headers).json()['data']['overview']['trainingCount'] == 0
    async def assert_removed():
        async with session_factory() as db:
            assert await db.get(TrainingSession, session_id) is None
            assert await db.get(ResumeContext, session_id) is None
            assert await db.scalar(select(func.count()).select_from(Message).where(Message.session_id == session_id)) == 0
            assert await db.scalar(select(func.count()).select_from(Evaluation).where(Evaluation.session_id == session_id)) == 0
    asyncio.run(assert_removed())


@pytest.mark.parametrize('channel', ['TEXT', 'VOICE', 'VIDEO'])
def test_one_answer_can_end_with_limited_summary_but_is_not_formal_growth(client, channel):
    headers = register(client)
    session_id = prepare(client, headers, channel)
    answer(client, headers, session_id, channel, 1)
    response = client.post(f'/api/v1/training-sessions/{session_id}/finish?create_plan=false', headers=headers)
    assert response.status_code == 200, response.text
    report = response.json()['data']
    assert report['summary'] and report['answeredRounds'] == 1
    assert report['qualityStatus'] == 'LIMITED_SAMPLE'
    assert report['eligibleForGrowth'] is False
    assert len(report['evidence']) == 4
    assert all(item['answer'] == ANSWER for item in report['evidence'])
    # Delayed/unload discard requests must preserve an explicitly ended interview.
    assert client.post(f'/api/v1/training-sessions/{session_id}/discard', headers=headers).status_code == 204
    reopened = client.get(f'/api/v1/evaluations/{session_id}', headers=headers)
    assert reopened.status_code == 200 and reopened.json()['data']['id'] == report['id']
    dashboard = client.get('/api/v1/dashboard', headers=headers).json()['data']
    assert dashboard['overview']['trainingCount'] == 1 and dashboard['formalEvaluationCount'] == 0


def test_empty_attempt_cannot_generate_invented_summary_and_discard_is_owned(client):
    headers, other = register(client), register(client)
    session_id = prepare(client, headers)
    assert client.post(f'/api/v1/training-sessions/{session_id}/discard', headers=other).status_code == 404
    assert client.post(f'/api/v1/training-sessions/{session_id}/discard').status_code == 401
    empty = client.post(f'/api/v1/training-sessions/{session_id}/finish', headers=headers)
    assert empty.status_code == 422 and empty.json()['title'] == 'TRAINING_ANSWERS_EMPTY'
    assert client.get(f'/api/v1/evaluations/{session_id}', headers=headers).status_code == 404
    assert client.post(f'/api/v1/training-sessions/{session_id}/discard', headers=headers).status_code == 204


def test_reply_arriving_after_exit_cannot_recreate_messages_or_state(client, monkeypatch):
    headers = register(client)
    session_id = prepare(client, headers)
    user_id = client.get('/api/v1/auth/me', headers=headers).json()['data']['id']
    async def late_reply(*args, **kwargs):
        async with session_factory() as db:
            await discard_training_session(db, user_id, session_id)
        yield '这是一条退出后才返回的模型回复。'
    monkeypatch.setattr(llm_gateway, 'stream_text', late_reply)
    client.post(f'/api/v1/training-sessions/{session_id}/messages/complete', headers=headers, json={'content': ANSWER})
    assert client.get(f'/api/v1/training-sessions/{session_id}', headers=headers).status_code == 404
    async def no_orphans():
        async with session_factory() as db:
            assert await db.scalar(select(func.count()).select_from(Message).where(Message.session_id == session_id)) == 0
    asyncio.run(no_orphans())
