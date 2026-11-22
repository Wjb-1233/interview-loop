"""把一次语音对练的转写文本落成一个训练会话，接上现有评分链路。"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from difflib import SequenceMatcher

from app.db.models import Message, Scene, TrainingSession
from app.features.scenes.service import get_scene
from app.features.scenes.taxonomy import normalize_bank


def _coverage(scene: Scene, questions: list[str], bank_override: list[dict] | None = None) -> int:
    """按文本相似度判断必问题是否真的被问到，而不是直接按轮次算。"""
    bank = normalize_bank(bank_override if bank_override is not None else scene.question_bank)
    if not bank or not questions:
        return 0
    covered = 0
    for item in bank:
        target = str(item.get("text", "")).strip()
        if not target:
            continue
        best = max(
            (SequenceMatcher(None, target, question).ratio() for question in questions),
            default=0.0,
        )
        if best >= 0.55:
            covered += 1
    return covered


async def create_voice_session(
    session: AsyncSession,
    user_id: str,
    scene_id: str,
    turns: list[dict],
    duration_seconds: int | None = None,
    delivery: dict | None = None,
    engine: str = "doubao",
    channel: str = "VOICE",
    recording_path: str | None = None,
    prepared_session_id: str | None = None,
) -> str:
    scene = await get_scene(session, scene_id, user_id)
    if not turns:
        raise AppError(422, "VOICE_SESSION_EMPTY", "这次通话没有可评分的对话内容")

    cleaned: list[tuple[str, str]] = []
    for turn in turns:
        question = str(turn.get("question", "")).strip()
        answer = str(turn.get("answer", "")).strip()
        if not answer:
            continue
        cleaned.append((question or "请继续。", answer))
    if not cleaned:
        raise AppError(422, "VOICE_SESSION_EMPTY", "这次通话没有可评分的回答")

    now = datetime.now(timezone.utc)
    training = TrainingSession(
        user_id=user_id,
        scene_id=scene.id,
        status="ACTIVE",
        stage="CLOSING",
        current_round=len(cleaned),
        covered_count=_coverage(scene, [question for question, _ in cleaned]),
        question_plan=normalize_bank(scene.question_bank),
        channel=channel,
        duration_seconds=duration_seconds,
        delivery={**(delivery or {}), "engine": engine},
        recording_path=recording_path,
        started_at=now,
    )
    from app.features.training.rubrics import new_context
    training.assessment_context = new_context(scene, normalize_bank(scene.question_bank))
    if prepared_session_id:
        prepared = await session.get(TrainingSession, prepared_session_id)
        if prepared is None or prepared.user_id != user_id or prepared.scene_id != scene_id:
            raise AppError(404, "SESSION_NOT_FOUND", "准备会话不存在")
        if prepared.current_round:
            existing = (await session.scalars(select(Message).where(Message.session_id == prepared.id).order_by(Message.round_no, Message.created_at))).all()
            old = [(next((m.content for m in existing if m.round_no == index and m.speaker == "AI"), ""), next((m.content for m in existing if m.round_no == index and m.speaker == "USER"), "")) for index in range(1, prepared.current_round + 1)]
            if old == cleaned and prepared.channel == channel:
                return prepared.id
            raise AppError(409, "SESSION_ALREADY_SAVED", "本场面试已保存，请查看训练记录")
        if prepared.status != "ACTIVE":
            raise AppError(409, "SESSION_ALREADY_SAVED", "本场面试已保存，请查看训练记录")
        from sqlalchemy import delete
        await session.execute(delete(Message).where(Message.session_id == prepared.id))
        prepared.current_round = len(cleaned)
        prepared.covered_count = _coverage(scene, [question for question, _ in cleaned], prepared.question_plan)
        prepared.channel = channel
        prepared.duration_seconds = duration_seconds
        prepared.delivery = {**(prepared.delivery or {}), **(training.delivery or {})}
        prepared.recording_path = recording_path
        training = prepared
    session.add(training)
    await session.flush()

    for index, (question, answer) in enumerate(cleaned, start=1):
        session.add(
            Message(
                session_id=training.id,
                round_no=index,
                speaker="AI",
                content=question,
            )
        )
        session.add(
            Message(
                session_id=training.id,
                round_no=index,
                speaker="USER",
                content=answer,
            )
        )

    await session.commit()
    return training.id


async def latest_scene_title(session: AsyncSession, scene_id: str) -> str:
    title = await session.scalar(select(Scene.title).where(Scene.id == scene_id))
    return title or "语音对练"
