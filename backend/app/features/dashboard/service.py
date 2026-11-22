from datetime import datetime, timedelta, timezone
from math import isfinite

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.core.errors import not_found
from app.db.models import Evaluation, ResumeContext, Scene, TrainingSession
from app.features.training.comparison_conditions import condition_filters
from app.features.dashboard.summary import training_summary
from app.features.evaluations.quality import formal_filters, training_order

SCORE_LABELS = {'logic': '内容与逻辑', 'relevance': '贴合问题', 'correctness': '信息完整', 'concision': '表达干净'}
RECENT_SAMPLES = 5
TREND_SAMPLES = 20
MIN_TREND_SAMPLES = 3


def scores(evaluation: Evaluation) -> dict:
    return {key: getattr(evaluation, f'{key}_score') for key in SCORE_LABELS}


def training_time(training: TrainingSession) -> datetime:
    value = training.finished_at or training.started_at
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def reference(training: TrainingSession, title: str, has_resume: bool = False) -> dict:
    return {'anchorSessionId': training.id, 'sceneId': training.scene_id, 'sceneTitle': title, 'channel': training.channel, 'depth': training.depth, 'mode': training.mode, 'hasResume': has_resume, 'hasJd': bool(training.jd_text), 'trainedAt': training_time(training).isoformat()}


async def overview(db: AsyncSession, user_id: str) -> dict:
    recent = func.coalesce(TrainingSession.finished_at, TrainingSession.started_at) >= datetime.now(timezone.utc) - timedelta(days=30)
    rows = (await db.execute(select(TrainingSession.channel, func.count(), func.sum(case((recent, 1), else_=0))).where(TrainingSession.user_id == user_id, TrainingSession.status == 'FINISHED').group_by(TrainingSession.channel))).all()
    counts = {key: 0 for key in ('TEXT', 'VOICE', 'VIDEO')}
    for channel, count, _ in rows:
        if channel in counts:
            counts[channel] = count
    return {'trainingCount': sum(row[1] for row in rows), 'recentTrainingCount': sum(int(row[2] or 0) for row in rows), 'recentDays': 30, 'channelCounts': counts}


def delivery_summary(training: TrainingSession | None) -> dict | None:
    if training is None or training.channel == 'TEXT':
        return None
    raw = training.delivery or {}
    def numbers(source, keys):
        return {key: value for key in keys if isinstance(value := source.get(key), (int, float)) and not isinstance(value, bool) and isfinite(value) and value >= 0}
    speech = numbers(raw, ('speechRate', 'pauseCount', 'longestPause', 'fillerTotal'))
    vision = raw.get('vision') or {}
    camera = numbers(vision, ('faceRatio', 'eyeContactRatio', 'headStability')) if isinstance(vision, dict) and vision.get('available') is not False else {}
    return {'sessionId': training.id, 'channel': training.channel, 'speech': speech, 'camera': camera}


async def dashboard_data(db: AsyncSession, user_id: str, channel: str | None = None, scene_id: str | None = None, anchor_session_id: str | None = None) -> dict:
    totals = await overview(db, user_id)
    formal = (Evaluation.user_id == user_id, TrainingSession.user_id == user_id, *formal_filters())
    ordering = training_order()
    # Filter choices come from the learner's actual scored history, including retired scenes.
    options = (await db.execute(select(TrainingSession, Scene.title).options(load_only(TrainingSession.id, TrainingSession.scene_id, TrainingSession.channel, TrainingSession.depth, TrainingSession.mode, TrainingSession.language, TrainingSession.jd_text, TrainingSession.started_at, TrainingSession.finished_at, TrainingSession.assessment_context)).join(Evaluation, Evaluation.session_id == TrainingSession.id).join(Scene, Scene.id == TrainingSession.scene_id).where(*formal).order_by(*ordering))).all()
    candidates = [row for row in options if (not channel or row[0].channel == channel) and (not scene_id or row[0].scene_id == scene_id)]
    selected = next((row for row in candidates if row[0].id == anchor_session_id), None) if anchor_session_id else next(iter(candidates), None)
    if anchor_session_id and selected is None:
        raise not_found('可比较的参考训练')
    matching = []
    total_matches = 0
    selected_resume = None
    if selected:
        context = await db.get(ResumeContext, selected[0].id)
        selected_resume = context.content if context else None
        query = select(Evaluation, TrainingSession).join(TrainingSession, TrainingSession.id == Evaluation.session_id).outerjoin(ResumeContext, ResumeContext.session_id == TrainingSession.id).where(*formal, *condition_filters(selected[0], selected_resume))
        total_matches = int(await db.scalar(select(func.count()).select_from(query.subquery())) or 0)
        matching = (await db.execute(query.order_by(*ordering).limit(TREND_SAMPLES))).all()
    recent = matching[:RECENT_SAMPLES]
    averages = {key: round(sum(getattr(item[0], f'{key}_score') for item in recent) / len(recent), 2) for key in SCORE_LABELS} if recent else {}
    latest, latest_training = matching[0] if matching else (None, None)
    tag_counts = {}
    for evaluation, _ in recent:
        for tag in evaluation.style_tags or []:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    return {
        'overview': totals, 'trainingCount': totals['trainingCount'],
        'condition': reference(selected[0], selected[1], selected_resume is not None) if selected else None,
        'filterOptions': {'scenes': list({row[0].scene_id: {'id': row[0].scene_id, 'title': row[1]} for row in options}.values()), 'anchors': [reference(row[0], row[1]) for row in candidates]},
        'formalEvaluationCount': total_matches, 'sampleCount': len(matching), 'recentSampleCount': len(recent), 'minimumTrendSamples': MIN_TREND_SAMPLES, 'trendReady': len(matching) >= MIN_TREND_SAMPLES,
        'latestScore': latest.overall_score if latest else None, 'latestSessionId': latest_training.id if latest_training else None, 'latestTrainingAt': training_time(latest_training).isoformat() if latest_training else None,
        'recentAverage': round(sum(item[0].overall_score for item in recent) / len(recent), 1) if recent else None,
        'dimensions': scores(latest) if latest else None, 'averageDimensions': averages or None,
        'styleTags': [f'{tag} ×{count}' for tag, count in sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))[:3]],
        'weaknesses': [{'dimension': SCORE_LABELS[key], 'averageScore': value, 'sampleCount': len(recent)} for key, value in sorted(averages.items(), key=lambda item: item[1])[:2]] if len(set(averages.values())) > 1 else [],
        'summary': training_summary(recent, averages, SCORE_LABELS),
        'trends': [{'sessionId': training.id, 'date': training_time(training).isoformat(), 'score': evaluation.overall_score, 'dimensions': scores(evaluation)} for evaluation, training in reversed(matching)],
        'delivery': delivery_summary(latest_training),
    }
