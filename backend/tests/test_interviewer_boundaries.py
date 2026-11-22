import asyncio

import pytest
from app.db.base import session_factory
from app.db.models import TrainingSession
from app.features.training.graph import safety_node
from app.features.training.service import is_nervous
from app.features.evaluations.objectives import evasive_ratio
from app.infrastructure.llm import llm_gateway
from tests.support.factories import client, register, model_response


def create(client, headers):
    response = client.post('/api/v1/training-sessions', headers=headers, json={'sceneId': 'scene-interview-03'})
    assert response.status_code == 201, response.text
    return response.json()['data']['id']


def answer(client, headers, session_id, text):
    response = client.post(f'/api/v1/training-sessions/{session_id}/messages/complete', headers=headers, json={'content': text})
    assert response.status_code == 200, response.text
    return response.json()['data']


@pytest.mark.parametrize('text', ['我不会说不关我的事，而会主动核实。', '我不会说“不关我的事”，而会主动协调。', '应该避免说你必须照我说的做。'])
def test_reflective_language_is_not_a_risk_label(text):
    assert safety_node({'user_text': text})['flags'] == []


def test_affirmative_risk_and_nervousness_are_preserved():
    assert safety_node({'user_text': '不关我的事，你必须照我说的做。'})['flags']
    assert is_nervous('我有点紧张。')
    assert not is_nervous('我不紧张，准备好了。')
    assert evasive_ratio(['我不知道，需要先查配置并用并发测试验证。']) == 0
    assert evasive_ratio(['不知道，随便。']) == 1


def test_repeat_is_retained_but_not_counted_in_statistics(client):
    headers = register(client)
    session_id = create(client, headers)
    answer(client, headers, session_id, '我负责订单接口，通过日志验证实际结果。')
    answer(client, headers, session_id, '请再说一遍')
    answer(client, headers, session_id, '我先做并发测试，再检查数据一致性与边界。')
    report = client.post(f'/api/v1/training-sessions/{session_id}/finish?create_plan=false', headers=headers).json()['data']
    assert report['answeredRounds'] == report['speechStats']['rounds'] == 2
    detail = client.get(f'/api/v1/training-sessions/{session_id}', headers=headers).json()['data']
    assert any(item['content'] == '请再说一遍' for item in detail['messages'])
    assert len(detail['answerTurns']) == 2


def test_hint_uses_actual_question_and_type(client, monkeypatch):
    headers = register(client)
    session_id = create(client, headers)

    async def set_plan():
        async with session_factory() as db:
            row = await db.get(TrainingSession, session_id)
            row.question_plan = [{'text': '解释数据库事务隔离原理？', 'dimension': '信息完整'}, {'text': '如何处理接口超时？'}]
            await db.commit()

    async def stream(*args, **kwargs):
        yield '解释数据库事务隔离原理？'

    asyncio.run(set_plan())
    monkeypatch.setattr(llm_gateway, 'stream_text', stream)
    reply = answer(client, headers, session_id, '我负责数据库与接口，通过日志验证了结果。')
    hint = client.post(f'/api/v1/training-sessions/{session_id}/hint', headers=headers).json()['data']
    assert hint['question'] == reply['content']
    assert hint['structure'][0].startswith('定义')


def test_conflicting_full_score_is_reviewed_and_excluded_until_repaired(client, monkeypatch):
    headers = register(client)
    session_id = create(client, headers)
    for _ in range(2):
        answer(client, headers, session_id, '我负责订单接口，通过日志验证结果并检查一致性边界。')

    async def inconsistent(system, prompt, **kwargs):
        result = await model_response(system, prompt, **kwargs)
        result['scores'] = {key: 5 for key in ['logic', 'relevance', 'correctness', 'concision']}
        row = result['evidence'][0]
        result['technicalChecks'] = [{**{key: row[key] for key in ['roundNo', 'quote']}, 'verdict': 'ERROR', 'reason': '重要原理有明确错误。'}]
        return result

    monkeypatch.setattr(llm_gateway, 'complete_json', inconsistent)
    response = client.post(f'/api/v1/training-sessions/{session_id}/finish?create_plan=false', headers=headers)
    assert response.status_code == 200, response.text
    original = response.json()['data']
    assert original['qualityStatus'] == 'REVIEW_REQUIRED'
    assert not original['eligibleForGrowth']
    assert original['assessment']['consistencyConflicts']
    assert client.get('/api/v1/dashboard', headers=headers).json()['data']['formalEvaluationCount'] == 0
    monkeypatch.setattr(llm_gateway, 'complete_json', model_response)
    repaired = client.post(f'/api/v1/evaluations/{session_id}?force=true', headers=headers).json()['data']
    assert repaired['id'] == original['id'] and repaired['revision'] == 2
    assert repaired['qualityStatus'] == 'VERIFIED' and repaired['eligibleForGrowth']
