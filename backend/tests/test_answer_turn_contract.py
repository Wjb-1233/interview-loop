import asyncio
import pytest
from app.db.base import session_factory
from app.db.models import Message, TrainingSession
from app.features.training.answer_turns import answer_turns
from tests.support.factories import client, register


@pytest.mark.parametrize('channel', ['TEXT', 'VOICE', 'VIDEO'])
def test_pairing_is_by_answer_round_not_message_list_position(channel):
    offset=1 if channel=='TEXT' else 0
    messages=[Message(id='q1',speaker='AI',round_no=1-offset,content='第一题'),Message(id='a1',speaker='USER',round_no=1,content='第一答'),Message(id='q2',speaker='AI',round_no=2-offset,content='第二题'),Message(id='a2',speaker='USER',round_no=2,content='第二答')]
    assert [(t.question.id,t.answer.id,t.round_no) for t in answer_turns(list(reversed(messages)),channel)]==[('q1','a1',1),('q2','a2',2)]


def test_repeat_request_does_not_replace_the_counted_answer():
    messages=[Message(id='q',speaker='AI',round_no=0,content='第一题'),Message(id='a',speaker='USER',round_no=1,content='已提交的回答'),Message(id='q2',speaker='AI',round_no=1,content='第二题'),Message(id='repeat',speaker='USER',round_no=1,content='请再说一遍')]
    assert answer_turns(messages,'TEXT')[0].answer.id=='a'


@pytest.mark.parametrize('old_channel,new_channel', [('TEXT','TEXT'),('VOICE','TEXT'),('TEXT','VIDEO'),('VIDEO','VOICE')])
def test_same_question_uses_matching_answer_for_all_channels(client, old_channel,new_channel):
    headers=register(client)
    user_id=client.get('/api/v1/auth/me',headers=headers).json()['data']['id']
    async def insert():
        async with session_factory() as db:
            ids=[]
            for channel in (old_channel,new_channel):
                training=TrainingSession(user_id=user_id,scene_id='scene-interview-03',channel=channel,status='FINISHED',current_round=2)
                db.add(training);await db.flush();ids.append(training.id)
                offset=1 if channel=='TEXT' else 0
                for n,(question,answer) in enumerate([('请介绍项目中的个人职责。','第一题：我负责接口设计。'),('解释数据库事务隔离原理。','第二题：隔离级别控制并发可见性。')],1):
                    db.add_all([Message(session_id=training.id,speaker='AI',round_no=n-offset,content=question),Message(session_id=training.id,speaker='USER',round_no=n,content=answer)])
            await db.commit();return ids
    previous,current=asyncio.run(insert())
    detail = client.get(f'/api/v1/training-sessions/{current}', headers=headers).json()['data']
    assert [turn['roundNo'] for turn in detail['answerTurns']] == [1, 2]
    assert detail['answerTurns'][0]['answer'].startswith('第一题')
    assert detail['answerTurns'][0]['question'] == '请介绍项目中的个人职责。'
    for number in (1,2):
        result=client.get(f'/api/v1/training-sessions/{current}/same-question/{number}',headers=headers)
        assert result.status_code==200,result.text
        attempts=result.json()['data']['attempts']
        assert len(attempts)==1 and attempts[0]['sessionId']==previous
        assert attempts[0]['roundNo']==number
        assert attempts[0]['answer'].startswith('第一题' if number==1 else '第二题')
