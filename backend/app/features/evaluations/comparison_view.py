"""两次训练的可视化对比：同一场景做四维逐轮全方位对比，不同场景只比通用指标。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import not_found
from app.db.models import Evaluation, Message, Scene, TrainingSession
from app.features.evaluations.quality import earlier_training, formal_filters, training_order
from app.features.evaluations.scoring import speech_statistics
from app.features.training.answer_turns import answer_turns

DIMENSIONS = [
    ("logic", "内容与逻辑"),
    ("relevance", "贴合问题"),
    ("correctness", "信息完整"),
    ("concision", "表达干净"),
]

# 通用指标：与场景无关，换场景也能横向对照
METRIC_LABELS = {
    "avgRoundLength": ("平均每题字数", "字", False),
    "avgSentenceLength": ("平均句长", "字", False),
    "fillerRate": ("口头语占比", "%", True),
    "flagCount": ("表达提醒次数", "次", True),
}

SCORE_STEP = 1  # 维度分差达到 1 分才算明显变化
RATE_STEP = 0.005  # 口头语占比变化 0.5 个百分点以上才算变化


async def _round_flags(session: AsyncSession, session_id: str, channel: str) -> dict[int, tuple[int, int]]:
    """按轮统计回答字数与表达提醒条数。"""
    messages = (
        await session.scalars(
            select(Message).where(Message.session_id == session_id).order_by(Message.round_no, Message.created_at)
        )
    ).all()
    result: dict[int, tuple[int, int]] = {}
    for turn in answer_turns(messages, channel):
        result[turn.round_no] = (len(turn.answer.content or ""), len(turn.answer.flags or []))
    return result


async def _snapshot(session: AsyncSession, evaluation: Evaluation) -> dict:
    training = await session.get(TrainingSession, evaluation.session_id)
    scene = await session.get(Scene, training.scene_id) if training else None
    messages = (
        await session.scalars(select(Message).where(Message.session_id == evaluation.session_id))
    ).all()
    speech = speech_statistics(messages, training.channel if training else None)
    rounds = await _round_flags(session, evaluation.session_id, training.channel if training else "TEXT")
    return {
        "sessionId": evaluation.session_id,
        "sceneId": training.scene_id if training else "",
        "sceneTitle": scene.title if scene else "",
        "channel": training.channel if training else "TEXT",
        "startedAt": training.started_at.isoformat() if training else evaluation.created_at.isoformat(),
        "durationSeconds": training.duration_seconds if training else None,
        "overallScore": evaluation.overall_score,
        "scores": {
            "logic": evaluation.logic_score,
            "relevance": evaluation.relevance_score,
            "correctness": evaluation.correctness_score,
            "concision": evaluation.concision_score,
        },
        "answeredRounds": speech.get("rounds", 0),
        "speech": {
            "avgRoundLength": speech.get("avgRoundLength", 0),
            "avgSentenceLength": speech.get("avgSentenceLength", 0),
            "fillerRate": speech.get("fillerRate", 0),
            "fillerTotal": speech.get("fillerTotal", 0),
            "flagCount": sum(item[1] for item in rounds.values()),
        },
        "rounds": rounds,
    }


async def _previous_evaluation(
    session: AsyncSession, current: Evaluation, current_training: TrainingSession
) -> Evaluation | None:
    """优先找同一场景的上一场，找不到再退回最近一次任意场景。"""
    base = (
        select(Evaluation)
        .join(TrainingSession, TrainingSession.id == Evaluation.session_id)
        .where(
            Evaluation.user_id == current.user_id,
            TrainingSession.user_id == current.user_id,
            Evaluation.id != current.id,
            earlier_training(current_training),
            *formal_filters(),
        )
    )
    same_scene = await session.scalar(
        base.where(TrainingSession.scene_id == current_training.scene_id).order_by(*training_order()).limit(1)
    )
    if same_scene is not None:
        return same_scene
    return await session.scalar(base.order_by(*training_order()).limit(1))


def _delta(current: float, previous: float) -> float:
    return round(current - previous, 3)


def _dimension_rows(current: dict, previous: dict) -> list[dict]:
    rows = []
    for key, label in DIMENSIONS:
        now = current["scores"][key]
        before = previous["scores"][key]
        rows.append({"key": key, "label": label, "current": now, "previous": before, "delta": now - before})
    return rows


def _metric_rows(current: dict, previous: dict) -> list[dict]:
    rows = []
    for key, (label, unit, lower_better) in METRIC_LABELS.items():
        now = current["speech"][key]
        before = previous["speech"][key]
        if unit == "%":
            now = round(now * 100, 1)
            before = round(before * 100, 1)
        rows.append(
            {
                "key": key,
                "label": label,
                "unit": unit,
                "current": now,
                "previous": before,
                "delta": _delta(now, before),
                "lowerIsBetter": lower_better,
                "neutral": key in {"avgRoundLength", "avgSentenceLength"},
            }
        )
    return rows


def _highlights(scope: str, dimensions: list[dict], metrics: list[dict], current: dict, previous: dict) -> tuple[list, list]:
    improved: list[dict] = []
    shortfalls: list[dict] = []

    if scope == "SAME_SCENE":
        for row in dimensions:
            if row["delta"] >= SCORE_STEP:
                improved.append({"label": row["label"], "detail": f"{row['previous']} → {row['current']} 分"})
            elif row["delta"] <= -SCORE_STEP:
                shortfalls.append({"label": row["label"], "detail": f"{row['previous']} → {row['current']} 分"})

    for row in metrics:
        if row["key"] == "fillerRate":
            if row["delta"] <= -RATE_STEP * 100:
                improved.append({"label": "口头语更少", "detail": f"{row['previous']}% → {row['current']}%"})
            elif row["delta"] >= RATE_STEP * 100:
                shortfalls.append({"label": "口头语变多", "detail": f"{row['previous']}% → {row['current']}%"})
        if row["key"] == "flagCount":
            if row["current"] < row["previous"]:
                improved.append({"label": "表达提醒减少", "detail": f"{row['previous']} → {row['current']} 次"})
            elif row["current"] > row["previous"]:
                shortfalls.append({"label": "表达提醒变多", "detail": f"{row['previous']} → {row['current']} 次"})

    now_total = current.get("overallScore") or 0
    before_total = previous.get("overallScore") or 0
    if scope != "SAME_SCENE":
        if now_total - before_total >= 1:
            improved.append({"label": "综合评分", "detail": f"{before_total} → {now_total} 分"})
        elif before_total - now_total >= 1:
            shortfalls.append({"label": "综合评分", "detail": f"{before_total} → {now_total} 分"})

    return improved[:4], shortfalls[:4]


def _summary(scope: str, current: dict, previous: dict, dimensions: list[dict], metrics: list[dict]) -> str:
    now_total = current.get("overallScore")
    before_total = previous.get("overallScore")
    if scope == "SAME_SCENE":
        head = f"本次与上一次同为「{current['sceneTitle']}」场景，综合评分{before_total} → {now_total}。"
        ups = [f"{row['label']}提高 {row['delta']} 分" for row in dimensions if row["delta"] >= SCORE_STEP]
        downs = [f"{row['label']}下降 {abs(row['delta'])} 分" for row in dimensions if row["delta"] <= -SCORE_STEP]
        middle = "四维中" + ("、".join(ups) + "；" if ups else "") + ("、".join(downs) + "。" if downs else "")
        if not ups and not downs:
            middle = "四维分数变化都在 1 分以内，属于正常波动。"
    else:
        head = (
            f"本次场景为「{current['sceneTitle']}」，上一次为「{previous['sceneTitle']}」，"
            f"题目与难度不同，只比较可以横向对照的通用指标。综合评分{before_total} → {now_total}。"
        )
        middle = ""
    filler = next((row for row in metrics if row["key"] == "fillerRate"), None)
    tail = ""
    if filler:
        tail = f"口头语占比从 {filler['previous']}% 变为 {filler['current']}%，平均每题 {current['speech']['avgRoundLength']:.0f} 字（上次 {previous['speech']['avgRoundLength']:.0f} 字）。"
    return head + middle + tail


async def build_comparison(session: AsyncSession, user_id: str, session_id: str) -> dict:
    training = await session.get(TrainingSession, session_id)
    if training is None or training.user_id != user_id:
        raise not_found("训练会话")
    evaluation = await session.scalar(select(Evaluation).where(Evaluation.session_id == session_id))
    if evaluation is None:
        raise not_found("评分报告")

    current = await _snapshot(session, evaluation)
    previous_evaluation = await _previous_evaluation(session, evaluation, training)
    if previous_evaluation is None:
        return {
            "scope": "NONE",
            "current": current,
            "previous": None,
            "dimensions": [],
            "metrics": [],
            "improvements": [],
            "shortfalls": [],
            "summary": "这是该场景的第一次训练，暂时没有可对比的上一场。下一场结束后会在这里给出进步与不足的分析。",
            "rounds": [],
        }

    previous = await _snapshot(session, previous_evaluation)
    scope = "SAME_SCENE" if previous["sceneId"] == current["sceneId"] else "DIFFERENT_SCENE"
    dimensions = _dimension_rows(current, previous) if scope == "SAME_SCENE" else []
    metrics = _metric_rows(current, previous)
    improved, shortfalls = _highlights(scope, dimensions, metrics, current, previous)

    rounds: list[dict] = []
    if scope == "SAME_SCENE":
        for round_no in sorted(set(current["rounds"]) & set(previous["rounds"])):
            now_chars, now_flags = current["rounds"][round_no]
            before_chars, before_flags = previous["rounds"][round_no]
            rounds.append(
                {
                    "roundNo": round_no,
                    "currentChars": now_chars,
                    "previousChars": before_chars,
                    "currentFlags": now_flags,
                    "previousFlags": before_flags,
                }
            )

    return {
        "scope": scope,
        "current": {key: value for key, value in current.items() if key != "rounds"},
        "previous": {key: value for key, value in previous.items() if key != "rounds"},
        "dimensions": dimensions,
        "metrics": metrics,
        "improvements": improved,
        "shortfalls": shortfalls,
        "summary": _summary(scope, current, previous, dimensions, metrics),
        "rounds": rounds,
    }
