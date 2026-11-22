"""评分可信度：矛盾分数在读取层标为不可用，表达风险字段落库并可读出。"""
import asyncio

from sqlalchemy import select

from app.db.base import session_factory
from app.db.models import Evaluation
from app.infrastructure.llm import llm_gateway
from tests.support.factories import client, model_response, register


def create(client, headers):
    response = client.post('/api/v1/training-sessions', headers=headers, json={'sceneId': 'scene-interview-03'})
    assert response.status_code == 201, response.text
    return response.json()['data']['id']


def answer(client, headers, session_id, text):
    response = client.post(f'/api/v1/training-sessions/{session_id}/messages/complete', headers=headers, json={'content': text})
    assert response.status_code == 200, response.text
    return response.json()['data']


def stored(session_id, field):
    async def read():
        async with session_factory() as db:
            row = await db.scalar(select(Evaluation).where(Evaluation.session_id == session_id))
            return getattr(row, field)
    return asyncio.run(read())


def test_contradictory_score_is_unavailable_in_report_but_kept_in_database(client, monkeypatch):
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
    report = response.json()['data']
    assert report['qualityStatus'] == 'REVIEW_REQUIRED'
    assert report['overallScore'] is None
    assert '矛盾' in report['scoreUnavailableReason'] and '暂不可用' in report['scoreUnavailableReason']
    # 四维分值照留，只是标为不可用；表达干净会被口头禅锚点压制，取整不参与断言。
    assert [report['scores'][key] for key in ('logic', 'relevance', 'correctness')] == [5, 5, 5]
    reopened = client.get(f'/api/v1/evaluations/{session_id}', headers=headers)
    assert reopened.status_code == 200 and reopened.json()['data']['overallScore'] is None
    frozen = 20.0 * sum(report['scores'][key] for key in ('logic', 'relevance', 'correctness', 'concision')) / 4
    assert stored(session_id, 'overall_score') == frozen and frozen > 0
    dashboard = client.get('/api/v1/dashboard', headers=headers)
    assert dashboard.status_code == 200 and dashboard.json()['data']['formalEvaluationCount'] == 0

    monkeypatch.setattr(llm_gateway, 'complete_json', model_response)
    repaired = client.post(f'/api/v1/evaluations/{session_id}?force=true', headers=headers).json()['data']
    assert isinstance(repaired['overallScore'], float) and repaired['scoreUnavailableReason'] is None
    assert repaired['qualityStatus'] != 'REVIEW_REQUIRED'
    assert repaired['revisionHistory'][0]['overallScore'] == frozen


def test_risk_flags_are_stored_and_returned(client, monkeypatch):
    headers = register(client)
    session_id = create(client, headers)
    for _ in range(2):
        answer(client, headers, session_id, '你必须马上交付，这和我没关系。')

    async def risky(system, prompt, **kwargs):
        result = await model_response(system, prompt, **kwargs)
        result['risk'] = ['命令式表达', '推卸责任', '命令式表达', '  ']
        return result

    monkeypatch.setattr(llm_gateway, 'complete_json', risky)
    report = client.post(f'/api/v1/training-sessions/{session_id}/finish?create_plan=false', headers=headers).json()['data']
    assert report['riskFlags'] == ['命令式表达', '推卸责任']
    assert stored(session_id, 'risk_flags') == ['命令式表达', '推卸责任']
    assert client.get(f'/api/v1/evaluations/{session_id}', headers=headers).json()['data']['riskFlags'] == ['命令式表达', '推卸责任']

    plain = create(client, headers)
    for _ in range(2):
        answer(client, headers, plain, '我负责订单接口，通过日志验证结果。')
    monkeypatch.setattr(llm_gateway, 'complete_json', model_response)
    assert client.post(f'/api/v1/training-sessions/{plain}/finish?create_plan=false', headers=headers).json()['data']['riskFlags'] == []
    assert stored(plain, 'risk_flags') == []
