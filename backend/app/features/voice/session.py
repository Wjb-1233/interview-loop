"""把一次语音对练的转写文本落成一个训练会话，接上现有评分链路。"""

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError

from app.db.models import Message, Scene, TrainingSession
from app.features.scenes.service import get_scene
from app.features.scenes.taxonomy import normalize_bank
from app.features.training.transcript import transcript_delivery
from app.features.training.question_coverage import covered_question_indexes


def _coverage(scene: Scene, questions: list[str], bank_override: list[dict] | None = None) -> int:
    """Use the same actual-question rule as text interviews and reports."""
    bank = normalize_bank(bank_override if bank_override is not None else scene.question_bank)
    return len(covered_question_indexes(bank, questions))


def _clean_turns(turns: list[dict]) -> tuple[list[tuple[str, str]], list[dict]]:
    """丢掉没有回答的轮次，返回 (问答对, 转写时间戳)。"""
    cleaned: list[tuple[str, str]] = []
    transcript = []
    for turn in turns:
        question = str(turn.get("question", "")).strip()
        answer = str(turn.get("answer", "")).strip()
        if not answer:
            continue
        cleaned.append((question or "请继续。", answer))
        transcript.append({"roundNo": len(cleaned), "startMs": turn.get("startMs"), "endMs": turn.get("endMs")})
    return cleaned, transcript


async def _same_dialogue_saved(session: AsyncSession, prepared: TrainingSession, cleaned: list[tuple[str, str]], channel: str) -> bool:
    """预建会话已有内容时，判断是否就是同一场对话的重复保存。"""
    existing = (await session.scalars(select(Message).where(Message.session_id == prepared.id).order_by(Message.round_no, Message.created_at))).all()
    old = [(next((m.content for m in existing if m.round_no == index and m.speaker == "AI"), ""), next((m.content for m in existing if m.round_no == index and m.speaker == "USER"), "")) for index in range(1, prepared.current_round + 1)]
    return old == cleaned and prepared.channel == channel


async def _adopt_prepared_session(
    session: AsyncSession, user_id: str, scene: Scene, prepared_session_id: str, training: TrainingSession,
    cleaned: list[tuple[str, str]], channel: str, duration_seconds: int | None, recording_path: str | None,
) -> tuple[TrainingSession, str | None]:
    """复用进房间时预建的会话。返回 (要落库的会话, 已保存时直接可返回的会话 id)。"""
    prepared = await session.get(TrainingSession, prepared_session_id)
    if prepared is None or prepared.user_id != user_id or prepared.scene_id != scene.id:
        raise AppError(404, "SESSION_NOT_FOUND", "准备会话不存在")
    if prepared.current_round:
        if await _same_dialogue_saved(session, prepared, cleaned, channel):
            return prepared, prepared.id
        raise AppError(409, "SESSION_ALREADY_SAVED", "本场面试已保存，请查看训练记录")
    if prepared.status != "ACTIVE":
        raise AppError(409, "SESSION_ALREADY_SAVED", "本场面试已保存，请查看训练记录")
    await session.execute(delete(Message).where(Message.session_id == prepared.id))
    prepared.current_round = len(cleaned)
    prepared.covered_count = _coverage(scene, [question for question, _ in cleaned], prepared.question_plan)
    prepared.channel = channel
    prepared.duration_seconds = duration_seconds
    prepared.delivery = {**(prepared.delivery or {}), **(training.delivery or {})}
    prepared.recording_path = recording_path
    return prepared, None


def _dialogue_messages(training_id: str, cleaned: list[tuple[str, str]]) -> list[Message]:
    messages = []
    for index, (question, answer) in enumerate(cleaned, start=1):
        messages.append(Message(session_id=training_id, round_no=index, speaker="AI", content=question))
        messages.append(Message(session_id=training_id, round_no=index, speaker="USER", content=answer))
    return messages


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
    cleaned, transcript = _clean_turns(turns)
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
        training, saved_id = await _adopt_prepared_session(
            session, user_id, scene, prepared_session_id, training, cleaned, channel, duration_seconds, recording_path
        )
        if saved_id:
            return saved_id
    session.add(training)
    await session.flush()

    messages = _dialogue_messages(training.id, cleaned)
    session.add_all(messages)
    await session.flush()
    training.delivery = transcript_delivery({**(training.delivery or {}), "transcript": transcript}, messages, channel)
    await session.commit()
    return training.id


async def latest_scene_title(session: AsyncSession, scene_id: str) -> str:
    title = await session.scalar(select(Scene.title).where(Scene.id == scene_id))
    return title or "语音对练"
