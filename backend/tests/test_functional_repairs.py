"""Regressions for the November 24 functional audit (no external AI/media calls)."""
import asyncio
import copy
import json

import pytest
from sqlalchemy import select

from app.db.base import session_factory
from app.db.models import Message, Scene, SkillState, TrainingPlan, TrainingSession
from app.features.training.evidence import OBSERVATION_PROMPT
from app.features.training.question_coverage import covered_question_indexes
from app.infrastructure.llm import llm_gateway
from tests.support.factories import client, register, model_response


ANSWER = '我负责接口设计，先分析业务约束，再用并发测试验证边界，并明确尚未验证的风险。'
QUESTIONS = ['请解释数据库事务的原子性及失败回滚机制。', '请说明缓存失效时如何处理并发更新和一致性边界。']


def test_one_question_does_not_cover_several_similar_required_items():
    bank = [{'text': '请说明你负责过的项目如何验证结果和失败边界？'},
            {'text': '请说明你参与过的项目如何验证结果和失败边界？'}]
    assert covered_question_indexes(bank, [bank[1]['text']]) == [1]
    assert covered_question_indexes(bank, ['请说明你的职业发展方向。']) == []
    assert covered_question_indexes(bank, [bank[0]['text'] + '（考察：信息完整）']) == [0]


def create(client, headers, **kwargs):
    response = client.post('/api/v1/training-sessions', headers=headers,
                          json={'sceneId': 'scene-interview-03', **kwargs})
    assert response.status_code == 201, response.text
    return response.json()['data']


def send(client, headers, sid):
    response = client.post(f'/api/v1/training-sessions/{sid}/messages/complete', headers=headers,
                          json={'content': ANSWER})
    assert response.status_code == 200, response.text
    return response.json()['data']


def mutate(sid, **values):
    async def write():
        async with session_factory() as db:
            training = await db.get(TrainingSession, sid)
            for key, value in values.items():
                setattr(training, key, value)
            await db.commit()
    asyncio.run(write())


@pytest.mark.parametrize('channel', ['VOICE', 'VIDEO'])
def test_saved_and_legacy_media_transcript_edits_correct_answer(client, channel):
    headers = register(client)
    turns = [{'question': q, 'answer': ANSWER, 'startMs': i * 5000, 'endMs': i * 5000 + 4000}
             for i, q in enumerate(QUESTIONS)]
    response = client.post('/api/v1/voice/sessions', headers=headers,
                           data={'sceneId': 'scene-interview-03', 'channelHint': channel, 'turns': json.dumps(turns)})
    assert response.status_code == 201, response.text
    sid = response.json()['data']['id']
    detail = client.get(f'/api/v1/training-sessions/{sid}', headers=headers).json()['data']
    transcript = detail['delivery']['transcript']
    assert [t['text'] for t in transcript] == [ANSWER, ANSWER]
    assert transcript[1]['startMs'] == 5000 and transcript[1]['endMs'] == 9000
    assert transcript[0]['answerMessageId'] == detail['answerTurns'][0]['answerMessageId']
    finished = client.post(f'/api/v1/training-sessions/{sid}/finish?create_plan=false', headers=headers)
    assert finished.status_code == 200, finished.text
    # Simulate an old record without a transcript, plus a same-round repeat control.
    mutate(sid, delivery={'engine': 'doubao', 'selfReview': [{'roundNo': 1, 'note': '保留自评'}]})
    async def add_control():
        async with session_factory() as db:
            db.add(Message(session_id=sid, round_no=1, speaker='USER', content='请再说一遍', kind='CONTROL'))
            await db.commit()
    asyncio.run(add_control())
    legacy = client.get(f'/api/v1/training-sessions/{sid}', headers=headers).json()['data']
    assert len(legacy['delivery']['transcript']) == 2
    async def stored_delivery():
        async with session_factory() as db:
            return copy.deepcopy((await db.get(TrainingSession, sid)).delivery)
    assert 'transcript' not in asyncio.run(stored_delivery())  # GET does not rewrite history.
    other = register(client)
    url = f'/api/v1/training-sessions/{sid}/transcript/1'
    assert client.patch(url, headers=headers, json={'text': '   '}).status_code == 422
    assert client.patch(url, headers=other, json={'text': '其他人不能改'}).status_code == 404
    edited = client.patch(url, headers=headers, json={'text': '我负责修正后的真实接口设计。'})
    assert edited.status_code == 200, edited.text
    current = client.get(f'/api/v1/training-sessions/{sid}', headers=headers).json()['data']
    assert current['answerTurns'][0]['answer'] == '我负责修正后的真实接口设计。'
    assert next(m['content'] for m in current['messages'] if m['content'] == '请再说一遍')
    assert current['delivery']['selfReview'][0]['note'] == '保留自评'
    report = client.get(f'/api/v1/evaluations/{sid}', headers=headers).json()['data']
    assert report['qualityStatus'] == 'PENDING_RESCORE' and not report['eligibleForGrowth']
    assert client.patch(f'/api/v1/training-sessions/{sid}/transcript/9', headers=headers, json={'text': ANSWER}).status_code == 404


@pytest.mark.parametrize('adaptive', [False, True])
def test_required_coverage_tracks_actual_questions_and_reply_contract(client, monkeypatch, adaptive):
    headers = register(client)
    item = create(client, headers, evidenceDriven=adaptive)
    sid = item['id']
    mutate(sid, question_plan=[{'text': q} for q in QUESTIONS], covered_count=2)
    async def observe(system, prompt, **kwargs):
        return {'observations': []} if system == OBSERVATION_PROMPT else await model_response(system, prompt, **kwargs)
    async def stream(system, messages):
        # A model that ignores the planned question must never earn coverage.
        yield '请先谈谈你的职业发展方向。'
    monkeypatch.setattr(llm_gateway, 'complete_json', observe)
    monkeypatch.setattr(llm_gateway, 'stream_text', stream)
    initial = client.get(f'/api/v1/training-sessions/{sid}', headers=headers).json()['data']
    assert initial['questionCovered'] == 0 and initial['coveredQuestionIndexes'] == []
    first = send(client, headers, sid)
    assert first['questionTotal'] == 2
    assert first['questionCovered'] == (1 if adaptive else 0)
    if adaptive:
        assert first['content'] == QUESTIONS[0]
        second = send(client, headers, sid)
        third = send(client, headers, sid)
        assert QUESTIONS[1] in [second['content'], third['content']]
        current = client.get(f'/api/v1/training-sessions/{sid}', headers=headers).json()['data']
        assert current['coveredQuestionIndexes'] == [0, 1]
        trace = current['assessmentContext']['evidenceTrace']
        assert [t['nextQuestion'] for t in trace] == [first['content'], second['content'], third['content']]
    else:
        assert first['coveredQuestionIndexes'] == []


@pytest.mark.parametrize('locked', ['FINISHED', 'STARTED', 'TRANSFER', 'RETEST'])
def test_fixed_conditions_reject_jd_replacement_and_removal(client, monkeypatch, locked):
    headers = register(client)
    item = create(client, headers)
    sid = item['id']
    values = {'jd_text': '原岗位要求', 'question_plan': [{'text': QUESTIONS[0]}]}
    if locked == 'FINISHED':
        values['status'] = 'FINISHED'
    elif locked == 'STARTED':
        values['current_round'] = 1
    elif locked == 'TRANSFER':
        values['assessment_context'] = {**item['assessmentContext'], 'purpose': 'TRANSFER'}
    else:
        async def retest():
            async with session_factory() as db:
                training = await db.get(TrainingSession, sid)
                plan = TrainingPlan(user_id=training.user_id, title='同条件复测', focus_dimension='内容与逻辑', tasks_version=2,
                                    tasks=[{'key': 'retest', 'actionType': 'RETEST', 'sourceSessionId': sid, 'completed': False}])
                db.add(plan)
                await db.flush()
                training.plan_id, training.task_key = plan.id, 'retest'
                await db.commit()
        asyncio.run(retest())
    mutate(sid, **values)
    async def forbidden(*args, **kwargs):
        pytest.fail('Locked edits must reject before requesting a new question plan')
    monkeypatch.setattr(llm_gateway, 'complete_json', forbidden)
    base = f'/api/v1/training-sessions/{sid}'
    assert client.post(base + '/jd', headers=headers, json={'jd_text': '负责简单接口开发，考察基础概念和个人项目介绍，不再考察原岗位要求。'}).status_code == 409
    assert client.delete(base + '/jd', headers=headers).status_code == 409
    current = client.get(base, headers=headers).json()['data']
    assert current['jdText'] == '原岗位要求' and current['questionPlan'][0]['text'] == QUESTIONS[0]
    assert not current['conditionsEditable'] and current['conditionsLockedReason']


def test_restart_preserves_frozen_configuration_and_resets_attempt_state(client):
    headers = register(client)
    old = create(client, headers, evidenceDriven=True)
    context = {**old['assessmentContext'], 'hintUses': 2, 'activeCriterionId': 'project',
               'evidenceTrace': [{'roundNo': 1}], 'coverage': {'project': {'本人职责': {'quote': ANSWER}}}}
    mutate(old['id'], assessment_context=context)
    # The scene can evolve after an attempt; restart must preserve the original rubric.
    async def edit_scene():
        async with session_factory() as db:
            scene = await db.get(Scene, old['sceneId'])
            before = copy.deepcopy(scene.question_bank)
            scene.question_bank = [{'text': '全新的题目', 'rubric': {'requiredPoints': ['新标准']}}]
            await db.commit()
            return before
    before = asyncio.run(edit_scene())
    try:
        response = client.post(f"/api/v1/training-sessions/{old['id']}/restart", headers=headers)
        assert response.status_code == 201, response.text
        new = response.json()['data']
        snapshot = new['assessmentContext']
        assert snapshot['adaptiveEnabled'] == context['adaptiveEnabled']
        assert snapshot['criteria'] == context['criteria'] and snapshot['rubricVersion'] == context['rubricVersion']
        assert snapshot['evidenceTrace'] == [] and snapshot['coverage'] == {} and snapshot['hintUses'] == 0
        assert not snapshot.get('activeCriterionId') and snapshot['purpose'] == 'PRACTICE'
        assert new['currentRound'] == 0 and new['id'] != old['id']
    finally:
        async def restore():
            async with session_factory() as db:
                scene = await db.get(Scene, old['sceneId'])
                scene.question_bank = before
                await db.commit()
        asyncio.run(restore())


@pytest.mark.parametrize('rounds', [1, 2])
def test_long_term_skills_require_formal_growth_qualification_once(client, rounds):
    headers = register(client)
    sid = create(client, headers)['id']
    for _ in range(rounds):
        send(client, headers, sid)
    report = client.post(f'/api/v1/training-sessions/{sid}/finish?create_plan=false', headers=headers).json()['data']
    user_id = client.get('/api/v1/auth/me', headers=headers).json()['data']['id']
    async def attempts():
        async with session_factory() as db:
            return [r.attempts for r in (await db.scalars(select(SkillState).where(SkillState.user_id == user_id))).all()]
    expected = [1] * 4 if rounds == 2 else []
    assert report['eligibleForGrowth'] == (rounds == 2)
    assert sorted(asyncio.run(attempts())) == expected
    assert client.post(f'/api/v1/training-sessions/{sid}/finish?create_plan=false', headers=headers).status_code == 200
    assert sorted(asyncio.run(attempts())) == expected


def test_repeat_and_sse_keep_actual_coverage_without_counting_control(client, monkeypatch):
    headers = register(client)
    sid = create(client, headers)['id']
    mutate(sid, question_plan=[{'text': q} for q in QUESTIONS])
    async def stream(system, messages):
        yield QUESTIONS[1]  # Coverage must identify the second question, not the first.
    monkeypatch.setattr(llm_gateway, 'stream_text', stream)
    reply = send(client, headers, sid)
    assert reply['coveredQuestionIndexes'] == [1] and reply['questionCovered'] == 1
    repeated = client.post(f'/api/v1/training-sessions/{sid}/messages/complete', headers=headers,
                           json={'content': '请再说一遍'}).json()['data']
    assert repeated['roundNo'] == 1 and repeated['coveredQuestionIndexes'] == [1]
    response = client.post(f'/api/v1/training-sessions/{sid}/messages', headers=headers, json={'content': ANSWER})
    assert response.status_code == 200
    assert '"coveredQuestionIndexes": [1]' in response.text
    current = client.get(f'/api/v1/training-sessions/{sid}', headers=headers).json()['data']
    assert current['questionCovered'] == 1 and current['currentRound'] == 2


def test_jd_generated_during_first_answer_cannot_replace_fixed_questions(client, monkeypatch):
    headers = register(client)
    sid = create(client, headers)['id']
    before = client.get(f'/api/v1/training-sessions/{sid}', headers=headers).json()['data']['questionPlan']
    async def race(*args, **kwargs):
        async with session_factory() as db:
            training = await db.get(TrainingSession, sid)
            training.current_round = 1
            await db.commit()
        return {'plan': [{'text': '偷偷替换的新问题'}]}
    monkeypatch.setattr(llm_gateway, 'complete_json', race)
    response = client.post(f'/api/v1/training-sessions/{sid}/jd', headers=headers,
                           json={'jd_text': '负责接口开发，需要理解数据库事务、并发控制与缓存的设计和验证方法。'})
    assert response.status_code == 409
    current = client.get(f'/api/v1/training-sessions/{sid}', headers=headers).json()['data']
    assert current['questionPlan'] == before and current['jdText'] is None


@pytest.mark.parametrize('kind', ['degraded', 'missing_evidence', 'transfer'])
def test_nonformal_reports_do_not_update_long_term_skills(client, monkeypatch, kind):
    headers = register(client)
    item = create(client, headers)
    for _ in range(2):
        send(client, headers, item['id'])
    if kind == 'transfer':
        mutate(item['id'], assessment_context={**item['assessmentContext'], 'purpose': 'TRANSFER'})
    async def grade(system, prompt, **kwargs):
        if kind == 'degraded':
            raise RuntimeError('offline')
        result = await model_response(system, prompt, **kwargs)
        if kind == 'missing_evidence':
            result['evidence'] = []
        return result
    monkeypatch.setattr(llm_gateway, 'complete_json', grade)
    result = client.post(f"/api/v1/training-sessions/{item['id']}/finish?create_plan=false", headers=headers)
    assert result.status_code == 200, result.text
    assert not result.json()['data']['eligibleForGrowth']
    user_id = client.get('/api/v1/auth/me', headers=headers).json()['data']['id']
    async def rows():
        async with session_factory() as db:
            return (await db.scalars(select(SkillState).where(SkillState.user_id == user_id))).all()
    assert asyncio.run(rows()) == []
