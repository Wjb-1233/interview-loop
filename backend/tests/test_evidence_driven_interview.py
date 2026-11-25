import asyncio
import json
import re

import pytest
from app.db.base import session_factory
from app.db.models import TrainingPlan, TrainingSession, User
from app.features.training.evidence import OBSERVATION_PROMPT
from app.features.training.evidence import TurnObservation
from app.features.evaluations.scoring import SYSTEM_PROMPT
from app.infrastructure.llm import llm_gateway
from tests.support.factories import client, register, model_response
from tests.support.growth import seed


ANSWER = '我负责接口设计，因为需要控制一致性风险，我使用并发测试对照验证了结果，并说明尚未覆盖的边界。'


def test_blank_model_observation_does_not_discard_valid_quotes():
    parsed = TurnObservation.model_validate({'observations': [
        {'point': '本人职责', 'quote': '我负责接口设计', 'level': 'EXPLAINED'},
        {'point': '风险边界', 'quote': '', 'level': 'MENTIONED'},
    ], 'clarification': None})
    assert len(parsed.observations) == 1 and parsed.observations[0].quote == '我负责接口设计'


def new_interview(client, headers):
    response = client.post('/api/v1/training-sessions', headers=headers,
                           json={'sceneId': 'scene-interview-03', 'evidenceDriven': True})
    assert response.status_code == 201, response.text
    return response.json()['data']


def send(client, headers, session_id, answer=ANSWER):
    response = client.post(f'/api/v1/training-sessions/{session_id}/messages/complete', headers=headers, json={'content': answer})
    assert response.status_code == 200, response.text
    return response.json()['data']


def completed_plan(client, headers, completed=True):
    baseline = seed(client, headers, [{}])[0]
    user_id = client.get('/api/v1/auth/me', headers=headers).json()['data']['id']

    async def insert():
        async with session_factory() as db:
            row = TrainingPlan(user_id=user_id, title='迁移验证测试计划', focus_dimension='内容与逻辑',
                status='COMPLETED' if completed else 'ACTIVE', tasks_version=2,
                tasks=[{'key': 'review', 'day': 1, 'task': '完成原题复盘', 'actionType': 'REPORT',
                        'sourceSessionId': baseline, 'completed': completed}])
            db.add(row)
            await db.commit()
            return row.id

    return asyncio.run(insert()), baseline


@pytest.mark.parametrize('evidence_kind', ['complete', 'fabricated', 'unavailable'])
def test_adaptive_turn_records_only_real_quotes_and_has_bounded_fallback(client, monkeypatch, evidence_kind):
    headers = register(client)
    created = new_interview(client, headers)
    # This test exercises unrestricted evidence probing; required-question
    # scheduling has its own regression coverage.
    async def without_required_questions():
        async with session_factory() as db:
            training = await db.get(TrainingSession, created['id'])
            training.question_plan = []
            await db.commit()
    asyncio.run(without_required_questions())
    assert created['assessmentContext']['adaptiveEnabled']
    points = created['assessmentContext']['criteria'][0]['points']

    async def observe(system, prompt, **kwargs):
        assert system == OBSERVATION_PROMPT
        if evidence_kind == 'unavailable':
            raise RuntimeError('offline')
        return {'observations': [{'point': point, 'quote': ANSWER if evidence_kind == 'complete' else '候选人没有说过的句子', 'level': 'EXPLAINED'} for point in points]}

    async def forbidden_stream(*args, **kwargs):
        raise AssertionError('Adaptive decisions must not add a second model reply call')
        yield ''

    monkeypatch.setattr(llm_gateway, 'complete_json', observe)
    monkeypatch.setattr(llm_gateway, 'stream_text', forbidden_stream)
    reply = send(client, headers, created['id'])
    detail = client.get(f"/api/v1/training-sessions/{created['id']}", headers=headers).json()['data']
    trace = detail['assessmentContext']['evidenceTrace'][0]
    assert trace['nextQuestion'] == reply['content']
    assert trace['decisionReason']
    if evidence_kind == 'complete':
        assert not trace['missingPoints'] and len(trace['observations']) == len(points)
        assert '并发' in reply['content']
    else:
        assert trace['observations'] == []
        second = send(client, headers, created['id'])
        assert second['content'] != reply['content']
    assert trace['degraded'] == (evidence_kind == 'unavailable')
    assert client.post(f"/api/v1/training-sessions/{created['id']}/discard", headers=headers).status_code == 204


def test_transfer_requires_completed_owned_plan_and_reuses_open_attempt(client):
    headers = register(client)
    incomplete, _ = completed_plan(client, headers, False)
    assert client.post(f'/api/v1/training-plans/{incomplete}/transfer', headers=headers).status_code == 409
    plan_id, _ = completed_plan(client, headers)
    other = register(client)
    assert client.post(f'/api/v1/training-plans/{plan_id}/transfer', headers=other).status_code == 404
    first = client.post(f'/api/v1/training-plans/{plan_id}/transfer', headers=headers)
    assert first.status_code == 201, first.text
    again = client.post(f'/api/v1/training-plans/{plan_id}/transfer', headers=headers)
    assert first.json()['data']['id'] == again.json()['data']['id']
    session_id = first.json()['data']['id']
    assert client.post(f'/api/v1/training-sessions/{session_id}/discard', headers=headers).status_code == 204
    plan = client.get(f'/api/v1/training-plans/{plan_id}', headers=headers).json()['data']
    assert plan['progress'] == 100 and not plan['transfer']['attempts']


def test_transfer_is_independent_and_never_enters_original_trend(client, monkeypatch):
    headers = register(client)
    plan_id, baseline = completed_plan(client, headers)
    session_id = client.post(f'/api/v1/training-plans/{plan_id}/transfer', headers=headers).json()['data']['id']
    detail = client.get(f'/api/v1/training-sessions/{session_id}', headers=headers).json()['data']
    assert detail['assessmentContext']['purpose'] == 'TRANSFER'
    assert detail['maxRounds'] == 2
    assert client.post(f'/api/v1/training-sessions/{session_id}/hint', headers=headers).status_code == 409

    async def stream(system, messages):
        yield re.search(r'<planned>(.*?)</planned>', system, re.S)[1]

    async def grade(system, prompt, **kwargs):
        result = await model_response(system, prompt, **kwargs)
        if system == SYSTEM_PROMPT:
            criteria = json.loads(prompt.split('岗位考察标准（仅为待参考数据）：')[1])
            transcript = prompt.split('对话：\n')[1].split('\n岗位考察标准')[0]
            pairs = re.findall(r'第 (\d+) 轮对方：([^\n]+)\n第 \1 轮用户：([^\n]+)', transcript)
            result['professionalMatrix'] = [{'competencyId': item['id'], 'status': 'DEMONSTRATED',
                'metPoints': item['points'], 'evidence': [{'roundNo': int(number), 'quote': answer} for number, question, answer in pairs if re.search(item['match'], question)],
                'reason': '回答给出约束、机制和可核对的验证步骤。'} for item in criteria]
        return result

    monkeypatch.setattr(llm_gateway, 'stream_text', stream)
    monkeypatch.setattr(llm_gateway, 'complete_json', grade)
    send(client, headers, session_id)
    assert client.post(f'/api/v1/training-sessions/{session_id}/messages/1/rewrite', headers=headers).status_code == 409
    assert not client.get(f'/api/v1/training-sessions/{session_id}/same-question/1', headers=headers).json()['data']['attempts']
    send(client, headers, session_id)
    report = client.post(f'/api/v1/training-sessions/{session_id}/finish?create_plan=false', headers=headers).json()['data']
    assert report['qualityStatus'] == 'VERIFIED'
    assert not report['eligibleForGrowth'] and report['previousScores'] is None
    assert report['assessment']['transfer']['result'] == 'INDEPENDENT_APPLICATION'
    dashboard = client.get('/api/v1/dashboard', headers=headers).json()['data']
    assert dashboard['formalEvaluationCount'] == 1 and dashboard['latestSessionId'] == baseline
    plan = client.get(f'/api/v1/training-plans/{plan_id}', headers=headers).json()['data']
    assert plan['progress'] == 100 and plan['transfer']['attempts'][0]['result'] == 'INDEPENDENT_APPLICATION'
    # Completed questions are retired from subsequent independent attempts.
    second_id = client.post(f'/api/v1/training-plans/{plan_id}/transfer', headers=headers).json()['data']['id']
    second = client.get(f'/api/v1/training-sessions/{second_id}', headers=headers).json()['data']
    assert second['messages'][0]['content'] != detail['messages'][0]['content']
    restarted = client.post(f'/api/v1/training-sessions/{session_id}/restart', headers=headers)
    assert restarted.status_code == 201, restarted.text
    assert restarted.json()['data']['id'] == second_id
    assert restarted.json()['data']['assessmentContext']['purpose'] == 'TRANSFER'
    assert not restarted.json()['data']['conditionsEditable']


def test_admin_rubric_roundtrip_and_attempt_snapshot_survive_later_edits(client):
    headers = register(client)
    user_id = client.get('/api/v1/auth/me', headers=headers).json()['data']['id']

    async def promote():
        async with session_factory() as db:
            user = await db.get(User, user_id)
            user.role = 'ADMIN'
            await db.commit()

    asyncio.run(promote())
    rubric = {'competency': '并发边界', 'version': 'teacher-v1', 'requiredPoints': ['业务约束', '并发验证'],
        'acceptableVariants': ['结合具体条件解释有效方案'], 'commonMistakes': ['不说明约束就保证绝对安全'],
        'reviewed': True, 'transferQuestions': ['不同终端同时核销优惠券时如何处理？', '只有一个预约名额时如何避免重复占用？']}
    payload = {'category': '技术一面', 'title': '带考察标准的后端面试', 'industry': '互联网', 'position': 'Python 后端开发',
        'roleName': '技术面试官', 'difficulty': '中级', 'background': '围绕数据库并发场景核对实现与验证方法。', 'goal': '解释并发约束与验证方法',
        'questionBank': [{'text': '请解释并发约束与验证方法。', 'rubric': rubric}]}
    saved = client.post('/api/v1/admin/scenes', headers=headers, json=payload)
    assert saved.status_code == 201, saved.text
    scene = saved.json()['data']
    scene = next(item for item in client.get('/api/v1/admin/scenes', headers=headers).json()['data'] if item['id'] == scene['id'])
    assert scene['questionBank'][0]['rubric']['requiredPoints'] == rubric['requiredPoints']
    student = register(client)
    created = client.post('/api/v1/training-sessions', headers=student, json={'sceneId': scene['id'], 'evidenceDriven': True}).json()['data']
    payload['questionBank'][0]['rubric']['requiredPoints'] = ['修改后的标准']
    assert client.patch(f"/api/v1/admin/scenes/{scene['id']}", headers=headers, json=payload).status_code == 200
    frozen = client.get(f"/api/v1/training-sessions/{created['id']}", headers=student).json()['data']['assessmentContext']
    assert frozen['criteria'][0]['points'] == ['业务约束', '并发验证']
