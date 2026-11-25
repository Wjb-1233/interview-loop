import asyncio
from datetime import datetime, timedelta, timezone
from app.db.base import session_factory
from app.db.models import Evaluation, EvaluationEvidence, Message, ResumeContext, TrainingSession

def seed(client, headers, records):
    user_id = client.get('/api/v1/auth/me', headers=headers).json()['data']['id']
    async def insert():
        ids = []
        async with session_factory() as db:
            for index, item in enumerate(records):
                # MySQL DATETIME stores whole seconds. Historical questions must
                # retain a distinct chronology even when fixtures are seeded fast.
                ended = datetime.now(timezone.utc) - timedelta(days=item.get('days', 0), seconds=len(records) - index)
                training = TrainingSession(user_id=user_id, scene_id=item.get('scene_id', 'scene-interview-03'), channel=item.get('channel', 'TEXT'), depth=item.get('depth', 'STANDARD'), mode=item.get('mode', 'STANDARD'), language=item.get('language', 'zh'), jd_text=item.get('jd_text'), status=item.get('status', 'FINISHED'), started_at=ended-timedelta(minutes=10), finished_at=ended, current_round=6, delivery=item.get('delivery'))
                db.add(training)
                await db.flush()
                if item.get('resume') is not None:
                    db.add(ResumeContext(session_id=training.id, filename='resume.docx', content=item['resume']))
                dimensions = item.get('dimensions', {'logic': 3, 'correctness': 3, 'relevance': 3, 'concision': 3})
                evaluation = Evaluation(session_id=training.id, user_id=user_id, overall_score=item.get('score', 60), **{f'{key}_score': value for key, value in dimensions.items()}, appropriateness_score=3, summary=item.get('summary', '测试评分'), suggestions=[], style_tags=['直接'], degraded=item.get('degraded', False), created_at=ended+timedelta(days=item.get('graded_later_days', 0)))
                db.add(evaluation)
                await db.flush()
                question = Message(session_id=training.id, round_no=0 if training.channel == 'TEXT' else 1, speaker='AI', content='请解释具体做法。', created_at=ended)
                answer = Message(session_id=training.id, round_no=1, speaker='USER', content='我通过监控验证结果，再检查一致性。', created_at=ended)
                db.add_all([question, answer])
                await db.flush()
                for dimension in item.get('evidence_dimensions', dimensions):
                    db.add(EvaluationEvidence(evaluation_id=evaluation.id, dimension=dimension, round_no=1, question_message_id=question.id, answer_message_id=answer.id, quote=item.get('quote', '我通过监控验证结果'), reason='原话给出了验证行动。', next_action='补充验证结果及边界。'))
                ids.append(training.id)
            await db.commit()
        return ids
    return asyncio.run(insert())

