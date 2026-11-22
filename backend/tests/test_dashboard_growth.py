from tests.support.growth import seed
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.db.base import session_factory
from app.db.models import Evaluation, EvaluationEvidence, Message, ResumeContext, TrainingSession
from tests.support.factories import client, register




@pytest.mark.parametrize('difference', [
    {'channel': 'VOICE'}, {'scene_id': 'scene-interview-01'}, {'depth': 'PRESSURE'},
    {'mode': 'DRILL'}, {'jd_text': '不同岗位要求'}, {'resume': '不同简历内容'},
])
def test_auto_matching_never_mixes_different_conditions(client, difference):
    headers = register(client)
    common = {'jd_text': '原岗位要求', 'resume': '原简历内容'}
    ids = seed(client, headers, [{**common, 'days': 3}, {**common, **difference, 'days': 2, 'score': 99}, {**common, 'days': 1, 'score': 65}])
    data = client.get('/api/v1/dashboard', headers=headers).json()['data']
    assert data['condition']['anchorSessionId'] == ids[2]
    assert data['formalEvaluationCount'] == 2
    assert [item['sessionId'] for item in data['trends']] == [ids[0], ids[2]]
    assert data['latestScore'] == 65 and data['recentAverage'] == 62.5
    assert data['overview']['trainingCount'] == 3
    assert data['trendReady'] is False


def test_overview_is_global_but_scores_follow_reference_and_training_time(client):
    headers = register(client)
    ids = seed(client, headers, [{'days': 45, 'score': 20, 'graded_later_days': 100}, {'days': 2, 'score': 60}, {'days': 1, 'channel': 'VOICE', 'score': 80}, {'days': 0, 'channel': 'VIDEO', 'degraded': True}, {'days': 0, 'status': 'ACTIVE'}])
    data = client.get('/api/v1/dashboard', headers=headers).json()['data']
    assert data['latestSessionId'] == ids[2]
    assert data['overview'] == {'trainingCount': 4, 'recentTrainingCount': 3, 'recentDays': 30, 'channelCounts': {'TEXT': 2, 'VOICE': 1, 'VIDEO': 1}}
    manual = client.get(f'/api/v1/dashboard?anchor_session_id={ids[0]}', headers=headers).json()['data']
    assert manual['latestSessionId'] == ids[1]
    assert manual['recentAverage'] == 40
    assert manual['overview'] == data['overview']
    empty = client.get('/api/v1/dashboard?channel=VIDEO', headers=headers).json()['data']
    assert empty['condition'] is None and empty['latestScore'] is None and empty['trends'] == []
    assert empty['overview']['trainingCount'] == 4


def test_sample_window_counts_and_latest_five_average(client):
    headers = register(client)
    ids = seed(client, headers, [{'days': 23-i, 'score': 30+i} for i in range(23)])
    data = client.get('/api/v1/dashboard', headers=headers).json()['data']
    assert data['formalEvaluationCount'] == 23 and data['sampleCount'] == 20
    assert data['recentSampleCount'] == 5 and data['recentAverage'] == 50
    assert data['latestSessionId'] == ids[-1]
    assert data['trends'][0]['sessionId'] == ids[3]
    assert data['trendReady'] is True


def test_reference_must_be_owned_formal_and_match_filters(client):
    owner, other = register(client), register(client)
    ids = seed(client, owner, [{'channel': 'VOICE'}, {'degraded': True}])
    assert client.get(f'/api/v1/dashboard?anchor_session_id={ids[0]}', headers=other).status_code == 404
    assert client.get(f'/api/v1/dashboard?anchor_session_id={ids[1]}', headers=owner).status_code == 404
    assert client.get(f'/api/v1/dashboard?channel=TEXT&anchor_session_id={ids[0]}', headers=owner).status_code == 404
    assert client.get('/api/v1/dashboard?channel=INVALID', headers=owner).status_code == 422


def test_empty_dashboard_does_not_invent_a_zero_score(client):
    data = client.get('/api/v1/dashboard', headers=register(client)).json()['data']
    assert data['latestScore'] is None and data['recentAverage'] is None
    assert data['condition'] is None
    assert 'retests' not in data
    assert data['trendReady'] is False and data['overview']['trainingCount'] == 0


def test_delivery_observations_are_separate_from_content_scores(client):
    headers = register(client)
    seed(client, headers, [{'channel': 'VIDEO', 'score': 65, 'delivery': {'speechRate': 180, 'pauseCount': 0, 'longestPause': 0, 'vision': {'faceRatio': 0.9, 'eyeContactRatio': 0.7}}}])
    data = client.get('/api/v1/dashboard', headers=headers).json()['data']
    assert data['delivery']['speech']['pauseCount'] == 0
    assert data['delivery']['camera']['faceRatio'] == 0.9
    assert data['latestScore'] == 65
    assert 'score' not in data['delivery']


def test_report_same_question_history_remains_available(client):
    headers = register(client)
    ids = seed(client, headers, [{'days': 2}, {'days': 1}])
    async def messages():
        async with session_factory() as db:
            for session_id, answer in zip(ids, ['原来的项目回答', '这次改进后的回答']):
                await db.execute(update(Message).where(Message.session_id==session_id, Message.round_no==0, Message.speaker=='AI').values(content='请介绍你负责的项目。'))
                await db.execute(update(Message).where(Message.session_id==session_id, Message.round_no==1, Message.speaker=='USER').values(content=answer))
            await db.commit()
    asyncio.run(messages())
    result = client.get(f'/api/v1/training-sessions/{ids[1]}/same-question/1', headers=headers)
    assert result.status_code == 200
    assert result.json()['data']['attempts'][0]['sessionId'] == ids[0]
    assert result.json()['data']['attempts'][0]['answer'] == '原来的项目回答'
    assert client.get(f'/api/v1/training-sessions/{ids[1]}/same-question/1', headers=register(client)).status_code == 404


def test_summary_uses_only_matching_formal_reports_and_gives_a_concrete_action(client, monkeypatch):
    async def no_model_call(*_args, **_kwargs):
        raise AssertionError('看板读取不应调用大模型')
    monkeypatch.setattr('app.infrastructure.llm.llm_gateway.complete_json', no_model_call)
    headers = register(client)
    seed(client, headers, [
        {'days': 3, 'score': 65, 'summary': '之前的复盘'},
        {'days': 2, 'channel': 'VIDEO', 'score': 100, 'summary': '不应混入的视频表现'},
        {'days': 1, 'score': 75, 'summary': '个人职责交代清楚，但结果缺少验证。', 'dimensions': {'logic': 4, 'correctness': 2, 'relevance': 4, 'concision': 3}},
        {'days': 0, 'degraded': True, 'summary': '不能当成正式成绩的规则复盘'},
    ])
    summary = client.get('/api/v1/dashboard?channel=TEXT', headers=headers).json()['data']['summary']
    assert summary['sampleCount'] == 2
    assert '70' in summary['text'] and '信息完整' in summary['text']
    assert '暂不判断趋势' in summary['text']
    assert summary['reportSummary'] == '个人职责交代清楚，但结果缺少验证。'
    assert '信息' in summary['nextAction'] or '题型' in summary['nextAction']
    assert '视频表现' not in str(summary) and '规则复盘' not in str(summary)


@pytest.mark.parametrize('records', [[], [{'degraded': True, 'summary': '规则评分不应冒充正式复盘'}]])
def test_summary_without_formal_samples_does_not_make_up_abilities(client, records):
    headers = register(client)
    seed(client, headers, records)
    summary = client.get('/api/v1/dashboard', headers=headers).json()['data']['summary']
    assert summary['sampleCount'] == 0 and summary['reportSummary'] is None
    assert '暂无正式评分' in summary['text']
    assert '0 分' not in summary['text'] and '提升了' not in summary['text']


def test_first_summary_cannot_claim_a_progress_trend_or_a_fake_weakness(client):
    headers = register(client)
    seed(client, headers, [{'score': 60}])
    data = client.get('/api/v1/dashboard', headers=headers).json()['data']
    assert data['summary']['sampleCount'] == 1
    assert '暂不判断趋势' in data['summary']['text']
    assert '没有明显的单一短板' in data['summary']['text']
    assert data['weaknesses'] == []


def test_summary_uses_latest_five_and_follows_filter_changes(client):
    headers = register(client)
    seed(client, headers, [{'days': 10-i, 'score': 50+i*5, 'summary': f'文字复盘{i}'} for i in range(7)] + [{'channel': 'VOICE', 'score': 90, 'summary': '语音复盘'}])
    text = client.get('/api/v1/dashboard?channel=TEXT', headers=headers).json()['data']['summary']
    voice = client.get('/api/v1/dashboard?channel=VOICE', headers=headers).json()['data']['summary']
    assert text['sampleCount'] == 5 and '70' in text['text']
    assert text['reportSummary'] == '文字复盘6'
    assert voice['sampleCount'] == 1 and voice['reportSummary'] == '语音复盘'
