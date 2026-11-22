import json
import pytest

from tests.support.factories import client, finish, register


def test_short_job_description_is_rejected_without_creating_a_session(client):
    headers = register(client)
    response = client.post('/api/v1/training-sessions/prepare', headers=headers, data={'sceneId': 'scene-interview-03', 'jd': '太短'})
    assert response.status_code == 422
    assert response.json()['title'] == 'JD_TOO_SHORT'
    assert client.get('/api/v1/training-sessions', headers=headers).json()['data'] == []


def test_transcript_edit_requires_finished_owned_session(client):
    headers = register(client)
    prepared = client.post('/api/v1/training-sessions/prepare', headers=headers, data={'sceneId': 'scene-interview-03', 'channel': 'VOICE'}).json()['data']
    url = f"/api/v1/training-sessions/{prepared['id']}/transcript/1"
    active = client.patch(url, headers=headers, json={'text': '修正后的回答'})
    assert active.status_code == 422 and active.json()['title'] == 'TRANSCRIPT_NOT_READY'
    assert client.patch(url, headers=register(client), json={'text': '其他用户不能改'}).status_code == 404


def test_finished_transcript_edit_updates_answer_and_marks_report_for_rescore(client):
    headers = register(client)
    prepared = client.post('/api/v1/training-sessions/prepare', headers=headers, data={'sceneId': 'scene-interview-03', 'channel': 'VOICE'}).json()['data']
    payload = {'sceneId': prepared['sceneId'], 'preparedSessionId': prepared['id'], 'turns': json.dumps([{'question': '你负责什么', 'answer': '原转写'}, {'question': '如何验证', 'answer': '检查监控结果'}])}
    assert client.post('/api/v1/voice/sessions', headers=headers, data=payload).status_code == 201
    assert client.post(f"/api/v1/training-sessions/{prepared['id']}/finish?create_plan=false", headers=headers).status_code == 200
    # 人工修正仅面向带逐轮转写的录像记录；普通实时语音仅有问答文本。
    import asyncio
    from app.db.base import session_factory
    from app.db.models import TrainingSession
    async def attach_transcript():
        async with session_factory() as db:
            training = await db.get(TrainingSession, prepared['id'])
            training.delivery = {**(training.delivery or {}), 'transcript': [{'roundNo': 1, 'text': '原转写'}]}
            await db.commit()
    asyncio.run(attach_transcript())
    edited = client.patch(f"/api/v1/training-sessions/{prepared['id']}/transcript/1", headers=headers, json={'text': '我负责接口设计，通过压测和监控验证结果。'})
    assert edited.status_code == 200 and edited.json()['data']['rescoreRequired'] is True
    detail = client.get(f"/api/v1/training-sessions/{prepared['id']}", headers=headers).json()['data']
    answer = next(item for item in detail['messages'] if item['roundNo'] == 1 and item['speaker'] == 'USER')
    assert answer['content'] == '我负责接口设计，通过压测和监控验证结果。'
    assert detail['delivery']['rescoreRequired'] is True


@pytest.mark.parametrize('channel', ['TEXT', 'VOICE'])
def test_same_timestamp_messages_still_replay_in_dialogue_order(client, channel):
    import asyncio
    from datetime import datetime, timezone
    from sqlalchemy import update
    from app.db.base import session_factory
    from app.db.models import Message
    headers = register(client)
    prepared = client.post('/api/v1/training-sessions/prepare', headers=headers, data={'sceneId': 'scene-interview-03', 'channel': channel}).json()['data']
    if channel == 'VOICE':
        client.post('/api/v1/voice/sessions', headers=headers, data={'sceneId': prepared['sceneId'], 'preparedSessionId': prepared['id'], 'turns': json.dumps([{'question': '第一个问题', 'answer': '第一轮回答'}, {'question': '第二个问题', 'answer': '第二轮回答'}])})
        expected = [(1, 'AI'), (1, 'USER'), (2, 'AI'), (2, 'USER')]
    else:
        for text in ['第一轮回答', '第二轮回答']:
            client.post(f"/api/v1/training-sessions/{prepared['id']}/messages/complete", headers=headers, json={'content': text})
        expected = [(0, 'AI'), (1, 'USER'), (1, 'AI'), (2, 'USER'), (2, 'AI')]
    async def same_time():
        async with session_factory() as db:
            await db.execute(update(Message).where(Message.session_id == prepared['id']).values(created_at=datetime(2026, 11, 14, tzinfo=timezone.utc)))
            await db.commit()
    asyncio.run(same_time())
    detail = client.get(f"/api/v1/training-sessions/{prepared['id']}", headers=headers).json()['data']
    assert [(m['roundNo'], m['speaker']) for m in detail['messages']] == expected


@pytest.mark.parametrize('channel', ['TEXT', 'VOICE'])
def test_report_question_types_match_the_question_for_each_answer(client, monkeypatch, channel):
    async def knowledge_followup(*_args, **_kwargs):
        yield '请解释事务的原子性。'
    monkeypatch.setattr('app.infrastructure.llm.llm_gateway.stream_text', knowledge_followup)
    headers = register(client)
    prepared = client.post('/api/v1/training-sessions/prepare', headers=headers, data={'sceneId': 'scene-interview-03', 'channel': channel}).json()['data']
    if channel == 'VOICE':
        client.post('/api/v1/voice/sessions', headers=headers, data={'sceneId': prepared['sceneId'], 'preparedSessionId': prepared['id'], 'turns': json.dumps([{'question': '请解释事务的原子性。', 'answer': '事务要么全部成功，要么全部回滚。'}, {'question': '介绍一个你负责过的项目。', 'answer': '我负责接口开发并通过压测验证结果。'}])})
        expected = ['KNOWLEDGE', 'EXPERIENCE']
    else:
        for answer in ['我负责接口开发并通过压测验证结果。', '事务要么全部成功，要么全部回滚。']:
            client.post(f"/api/v1/training-sessions/{prepared['id']}/messages/complete", headers=headers, json={'content': answer})
        expected = ['EXPERIENCE', 'KNOWLEDGE']
    result = client.post(f"/api/v1/training-sessions/{prepared['id']}/finish?create_plan=false", headers=headers).json()['data']
    assert result['questionTypes'] == [{'roundNo': index, 'type': kind} for index, kind in enumerate(expected, 1)]


def make_plan(client, headers):
    original = client.post('/api/v1/training-sessions/prepare', headers=headers, data={'sceneId': 'scene-interview-03', 'depth': 'PRESSURE', 'jd': '后端岗位要求熟悉 Python 接口开发、数据库设计、Redis 缓存和性能监控验证。'}).json()['data']
    finish(client, headers, original['id'])
    plan = client.get('/api/v1/training-plans', headers=headers).json()['data'][0]
    return original, plan


def test_restart_keeps_depth_and_job_context(client):
    headers = register(client)
    original, _ = make_plan(client, headers)
    restarted = client.post(f"/api/v1/training-sessions/{original['id']}/restart", headers=headers)
    assert restarted.status_code == 201
    data = restarted.json()['data']
    assert data['id'] != original['id']
    assert data['depth'] == original['depth']
    assert data['jdText'] == original['jdText']
    assert data['questionPlan'] == original['questionPlan']


def test_retest_cannot_start_before_learning_tasks(client):
    headers = register(client)
    original, plan = make_plan(client, headers)
    result = client.post('/api/v1/training-sessions/prepare', headers=headers, data={'sceneId': original['sceneId'], 'planId': plan['id'], 'taskKey': 'retest'})
    assert result.status_code == 422
    assert result.json()['title'] == 'PREVIOUS_TASK_INCOMPLETE'
    assert len(client.get('/api/v1/training-sessions', headers=headers).json()['data']) == 1


def test_plan_task_cannot_start_an_unrelated_scene(client):
    headers = register(client)
    original, plan = make_plan(client, headers)
    result = client.post('/api/v1/training-sessions/prepare', headers=headers, data={'sceneId': 'scene-interview-01', 'planId': plan['id'], 'taskKey': 'retest'})
    assert result.status_code == 422
    assert len(client.get('/api/v1/training-sessions', headers=headers).json()['data']) == 1


def test_voice_save_can_retry_after_scoring_failure(client):
    headers = register(client)
    prepared = client.post('/api/v1/training-sessions/prepare', headers=headers, data={'sceneId': 'scene-interview-03', 'channel': 'VOICE'}).json()['data']
    payload = {'sceneId': prepared['sceneId'], 'preparedSessionId': prepared['id'], 'turns': json.dumps([{'question': '做过什么项目', 'answer': '我负责接口设计'}, {'question': '如何验证', 'answer': '对比监控指标'}])}
    saved = client.post('/api/v1/voice/sessions', headers=headers, data=payload)
    assert saved.status_code == 201
    again = client.post('/api/v1/voice/sessions', headers=headers, data=payload)
    assert again.status_code == 201
    assert again.json()['data']['id'] == saved.json()['data']['id']
    detail = client.get(f"/api/v1/training-sessions/{prepared['id']}", headers=headers).json()['data']
    assert detail['currentRound'] == 2 and len(detail['messages']) == 4
    payload['turns'] = json.dumps([{'question': '不同的题目', 'answer': '修改后的作答'}])
    assert client.post('/api/v1/voice/sessions', headers=headers, data=payload).status_code == 409


def test_session_detail_keeps_plan_identity_for_history_resume(client):
    from tests.plan_task_helper import add_scene_task
    headers = register(client)
    original, plan = make_plan(client, headers)
    key = add_scene_task(plan['id'], original['sceneId'])
    result = client.post('/api/v1/training-sessions', headers=headers, json={'sceneId': original['sceneId'], 'planId': plan['id'], 'taskKey': key})
    assert result.status_code == 201
    detail = client.get(f"/api/v1/training-sessions/{result.json()['data']['id']}", headers=headers).json()['data']
    assert detail['planId'] == plan['id'] and detail['taskKey'] == key
    context = client.get(f"/api/v1/training-sessions/{detail['id']}/interview-context", headers=headers).json()['data']
    assert context['minimumRounds'] == 1
    assert context['planMinimumRounds'] == 6
