"""Prepare blind session-level labels; never synthesize human judgments."""
import hashlib
import random
from sqlalchemy import select
from app.db.models import Evaluation, Message, TrainingSession, User
from app.features.evaluations.quality import formal_filters
from app.features.training.answer_turns import answer_turns
from app.features.training.message_order import dialogue_order

LABELS = {'logic': '内容与逻辑', 'relevance': '贴合问题', 'correctness': '信息完整', 'concision': '表达干净'}


async def collect_blind(db, size: int, email: str | None = None) -> tuple[list[dict], list[dict]]:
    query = select(Evaluation, TrainingSession).join(TrainingSession, TrainingSession.id == Evaluation.session_id)
    query = query.join(User, User.id == Evaluation.user_id).where(*formal_filters())
    if email:
        query = query.where(User.email == email)
    candidates = (await db.execute(query.order_by(Evaluation.id))).all()
    random.Random(20261117).shuffle(candidates)
    annotations, key = [], []
    for evaluation, training in candidates[:size]:
        messages = (await db.scalars(select(Message).where(Message.session_id == training.id)
            .order_by(*dialogue_order(training.channel)))).all()
        conversation = '\n\n'.join(f'第 {turn.round_no} 轮\n问：{turn.question.content}\n答：{turn.answer.content}'
                                    for turn in answer_turns(messages, training.channel))
        group = hashlib.sha256(f'{evaluation.id}:{len(evaluation.revision_history or [])}'.encode()).hexdigest()[:12]
        for dimension, label in LABELS.items():
            sample_id = f'{group}-{dimension}'
            annotations.append({'sample_id': sample_id, 'dimension': label, 'conversation': conversation,
                                'human_score': '', 'note': ''})
            key.append({'sample_id': sample_id, 'group_id': group, 'dimension': label,
                        'model_score': getattr(evaluation, f'{dimension}_score'),
                        'model_version': (evaluation.assessment or {}).get('model', 'historical-unknown'),
                        'rubric_version': (evaluation.assessment or {}).get('rubricVersion', 'legacy'),
                        'session_id': training.id})
    return annotations, key
