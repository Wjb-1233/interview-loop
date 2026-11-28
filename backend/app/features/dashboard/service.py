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


async def _scored_history(db: AsyncSession, formal: tuple, ordering) -> list:
    # Filter choices come from the learner's actual scored history, including retired scenes.
    return (await db.execute(select(TrainingSession, Scene.title).options(load_only(TrainingSession.id, TrainingSession.scene_id, TrainingSession.channel, TrainingSession.depth, TrainingSession.mode, TrainingSession.language, TrainingSession.jd_text, TrainingSession.started_at, TrainingSession.finished_at, TrainingSession.assessment_context)).join(Evaluation, Evaluation.session_id == TrainingSession.id).join(Scene, Scene.id == TrainingSession.scene_id).where(*formal).order_by(*ordering))).all()


async def _matching_samples(db: AsyncSession, selected: tuple, formal: tuple, ordering) -> tuple[str | None, int, list]:
    """同条件的正式评分样本：返回 (参考简历, 总匹配数, 最近 TREND_SAMPLES 条)。"""
    context = await db.get(ResumeContext, selected[0].id)
    resume = context.content if context else None
    query = select(Evaluation, TrainingSession).join(TrainingSession, TrainingSession.id == Evaluation.session_id).outerjoin(ResumeContext, ResumeContext.session_id == TrainingSession.id).where(*formal, *condition_filters(selected[0], resume))
    total = int(await db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = (await db.execute(query.order_by(*ordering).limit(TREND_SAMPLES))).all()
    return resume, total, rows


def _recent_aggregates(recent: list) -> tuple[dict, list[str]]:
    """近期样本的四维均分与风格标签（最多 3 个）。"""
    averages = {key: round(sum(getattr(item[0], f'{key}_score') for item in recent) / len(recent), 2) for key in SCORE_LABELS} if recent else {}
    tag_counts = {}
    for evaluation, _ in recent:
        for tag in evaluation.style_tags or []:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    tags = [f'{tag} ×{count}' for tag, count in sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))[:3]]
    return averages, tags


def _select_reference(candidates: list, anchor_session_id: str | None):
    if not anchor_session_id:
        return next(iter(candidates), None)
    selected = next((row for row in candidates if row[0].id == anchor_session_id), None)
    if selected is None:
        raise not_found('可比较的参考训练')
    return selected


async def dashboard_data(db: AsyncSession, user_id: str, channel: str | None = None, scene_id: str | None = None, anchor_session_id: str | None = None) -> dict:
    totals = await overview(db, user_id)
    formal = (Evaluation.user_id == user_id, TrainingSession.user_id == user_id, *formal_filters())
    ordering = training_order()
    options = await _scored_history(db, formal, ordering)
    candidates = [row for row in options if (not channel or row[0].channel == channel) and (not scene_id or row[0].scene_id == scene_id)]
    selected = _select_reference(candidates, anchor_session_id)
    selected_resume, total_matches, matching = (await _matching_samples(db, selected, formal, ordering)) if selected else (None, 0, [])
    recent = matching[:RECENT_SAMPLES]
    averages, style_tags = _recent_aggregates(recent)
    latest, latest_training = matching[0] if matching else (None, None)
    return {
        'overview': totals, 'trainingCount': totals['trainingCount'],
        'condition': reference(selected[0], selected[1], selected_resume is not None) if selected else None,
        'filterOptions': {'scenes': list({row[0].scene_id: {'id': row[0].scene_id, 'title': row[1]} for row in options}.values()), 'anchors': [reference(row[0], row[1]) for row in candidates]},
        'formalEvaluationCount': total_matches, 'sampleCount': len(matching), 'recentSampleCount': len(recent), 'minimumTrendSamples': MIN_TREND_SAMPLES, 'trendReady': len(matching) >= MIN_TREND_SAMPLES,
        'latestScore': latest.overall_score if latest else None, 'latestSessionId': latest_training.id if latest_training else None, 'latestTrainingAt': training_time(latest_training).isoformat() if latest_training else None,
        'recentAverage': round(sum(item[0].overall_score for item in recent) / len(recent), 1) if recent else None,
        'dimensions': scores(latest) if latest else None, 'averageDimensions': averages or None,
        'styleTags': style_tags,
        'weaknesses': [{'dimension': SCORE_LABELS[key], 'averageScore': value, 'sampleCount': len(recent)} for key, value in sorted(averages.items(), key=lambda item: item[1])[:2]] if len(set(averages.values())) > 1 else [],
        'summary': training_summary(recent, averages, SCORE_LABELS),
        'trends': [{'sessionId': training.id, 'date': training_time(training).isoformat(), 'score': evaluation.overall_score, 'dimensions': scores(evaluation)} for evaluation, training in reversed(matching)],
        'delivery': delivery_summary(latest_training),
    }
