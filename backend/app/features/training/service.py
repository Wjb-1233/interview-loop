import re
import asyncio
import json
import logging
from collections.abc import AsyncIterator, Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError, not_found
from app.features.training.message_order import dialogue_order
from app.features.training.policy import MIN_REPORT_ROUNDS
from app.features.training.answer_turns import answer_turns
from app.features.training.transcript import transcript_delivery
from app.features.training.conditions import conditions_locked_reason, require_editable_conditions
from app.features.training.question_coverage import covered_question_indexes, dialogue_questions
from app.features.training.language import affirmative_occurrences, is_repeat_request, REPEAT_PATTERN
from app.features.training.schemas import AnswerTurnView
from app.db.base import session_factory
from app.features.recordings import storage
from app.db.models import Evaluation, EvaluationEvidence, Message, ResumeContext, Scene, TrainingPlan, TrainingSession
from app.features.scenes.service import get_scene
from app.features.scenes.taxonomy import normalize_bank
from app.features.training.job_match import build_match
from app.features.training.graph import conversation_graph
from app.features.training.hint_keywords import build_hint_keywords
from app.features.training.resume import opening_question
from app.features.training.schemas import (
    MessageRewriteView,
    MessageView,
    SessionView,
    TrainingHistoryItem,
    TurnReplyView,
)
from app.infrastructure.llm import llm_gateway

logger = logging.getLogger(__name__)


NERVOUS_PATTERN = re.compile(r"(紧张|有点慌|害怕|焦虑|nervous|anxious|panic)", re.IGNORECASE)


def is_nervous(text: str) -> bool:
    return bool(affirmative_occurrences(text or "", NERVOUS_PATTERN))


async def _startable_plan_task(session: AsyncSession, user_id: str, scene_id: str, plan_id: str, task_key: str) -> dict:
    """校验计划任务可以在该场景发起训练，返回任务。"""
    plan = await session.get(TrainingPlan, plan_id)
    if plan is None or plan.user_id != user_id:
        raise not_found("训练计划")
    from app.features.plans.service import validated_plan_tasks
    tasks = await validated_plan_tasks(session, plan)
    task = next((item for item in tasks if item.get("key") == task_key), None)
    if task is None:
        raise not_found("计划任务")
    if task.get("completed"):
        raise AppError(409, "TASK_COMPLETED", "这项任务已经完成过了")
    if task["actionType"] not in {"TRAINING", "RETEST", "SCENE", "VIDEO", "VOICE"}:
        raise AppError(422, "TASK_NOT_TRAINING", "这项任务不需要创建面试")
    if task.get("sceneId") and task["sceneId"] != scene_id:
        raise AppError(422, "SCENE_MISMATCH", "请在计划指定的场景完成训练")
    if any(not item["completed"] for item in tasks[:tasks.index(task)]):
        raise AppError(422, "PREVIOUS_TASK_INCOMPLETE", "请先完成前面的计划任务")
    return task


async def _training_opening(
    scene: Scene, resume_filename: str | None, resume_text: str | None
) -> tuple[str, bool]:
    if resume_filename and resume_text:
        return await opening_question(scene, resume_text)
    opening = (scene.opening_line or "").strip()
    if not opening:
        # A scene without a preset can start without a model request.
        opening = f"你好，我是{scene.role_name}，今天这场是{scene.category}，请先做个自我介绍。"
    return opening, False


async def create_training_session(
    session: AsyncSession,
    user_id: str,
    scene_id: str,
    resume_filename: str | None = None,
    resume_text: str | None = None,
    mode: str = "STANDARD",
    plan_id: str | None = None,
    task_key: str | None = None,
    depth: str = "STANDARD",
    language: str = "zh",
    channel: str = "TEXT",
    jd_text: str | None = None,
    question_plan: list[dict] | None = None,
    job_match: dict | None = None,
    evidence_driven: bool = False,
    assessment_template: dict | None = None,
) -> SessionView:
    if language != "zh":
        raise AppError(422, "LANGUAGE_UNSUPPORTED", "当前仅支持中文面试")
    scene = await get_scene(session, scene_id, user_id)
    if mode == "DRILL" and scene.difficulty != "进阶":
        raise AppError(422, "DRILL_REQUIRES_ADVANCED", "深挖模式只在进阶难度场景开放")
    if resume_text and scene.category == "基础能力提升":
        raise AppError(422, "RESUME_NOT_APPLICABLE", "四维基础练习不需要上传简历，请直接开始训练")
    if bool(plan_id) != bool(task_key):
        raise AppError(422, "PLAN_TASK_REQUIRED", "训练计划和任务编号需要同时提供")
    baseline = None
    if plan_id:
        task = await _startable_plan_task(session, user_id, scene_id, plan_id, task_key)
        if task["actionType"] == "RETEST":
            baseline = await session.get(TrainingSession, task.get("sourceSessionId"))
            if baseline is None or baseline.user_id != user_id:
                raise not_found("复测原会话")
            channel, depth, mode = baseline.channel, baseline.depth, baseline.mode
            jd_text, question_plan, job_match = baseline.jd_text, baseline.question_plan, baseline.job_match
            source_resume = await session.get(ResumeContext, baseline.id)
            resume_filename = source_resume.filename if source_resume else None
            resume_text = source_resume.content if source_resume else None
        elif task["actionType"] in {"VOICE", "VIDEO"}:
            channel = task["actionType"]
    opening_line, opening_degraded = await _training_opening(scene, resume_filename, resume_text)

    training = TrainingSession(
        user_id=user_id,
        scene_id=scene.id,
        plan_id=plan_id,
        task_key=task_key,
        channel=channel,
        jd_text=jd_text,
        question_plan=normalize_bank(question_plan if question_plan is not None else scene.question_bank),
        job_match=job_match,
        mode=mode if mode in {"STANDARD", "DRILL"} else "STANDARD",
        depth=depth if depth in {"STANDARD", "THREE_LAYER", "PRESSURE"} else "STANDARD",
        language="zh",
        max_rounds=settings.max_training_rounds,
    )
    from app.features.training.rubrics import new_context, fresh_context
    training.assessment_context = new_context(scene, normalize_bank(question_plan or scene.question_bank), evidence_driven)
    if assessment_template is not None:
        training.assessment_context = fresh_context(assessment_template)
    if baseline is not None:
        training.assessment_context = fresh_context(baseline.assessment_context)
    session.add(training)
    await session.flush()
    opening = Message(
        session_id=training.id,
        round_no=0,
        speaker="AI",
        content=opening_line,
    )
    session.add(opening)
    if resume_filename and resume_text:
        session.add(ResumeContext(
            session_id=training.id,
            filename=resume_filename,
            content=resume_text,
            opening_degraded=opening_degraded,
        ))
    await session.commit()
    return await get_training_session(session, user_id, training.id)


async def get_training_session(
    session: AsyncSession, user_id: str, session_id: str
) -> SessionView:
    training = await session.get(TrainingSession, session_id)
    if training is None or training.user_id != user_id:
        raise not_found("训练会话")
    scene = await session.get(Scene, training.scene_id)
    resume = await session.get(ResumeContext, training.id)
    messages = (
        await session.scalars(
            select(Message)
            .where(Message.session_id == training.id)
            .order_by(*dialogue_order(training.channel))
        )
    ).all()
    locked_reason = await conditions_locked_reason(session, training)
    bank = normalize_bank(training.question_plan if training.question_plan is not None else (scene.question_bank if scene else []))
    covered = covered_question_indexes(bank, dialogue_questions(messages))
    return SessionView(
        id=training.id,
        conditions_editable=locked_reason is None,
        conditions_locked_reason=locked_reason,
        assessment_context=training.assessment_context,
        scene_id=training.scene_id,
        scene_title=scene.title if scene else None,
        status=training.status,
        stage=training.stage,
        current_round=training.current_round,
        max_rounds=training.max_rounds,
        channel=training.channel,
        plan_id=training.plan_id,
        task_key=training.task_key,
        mode=training.mode or "STANDARD",
        depth=training.depth or "STANDARD",
        language=training.language or "zh",
        duration_seconds=training.duration_seconds,
        delivery=transcript_delivery(training.delivery, messages, training.channel),
        recording_url=storage.url_of(training.recording_path),
        started_at=training.started_at,
        finished_at=training.finished_at,
        archived_at=training.archived_at,
        resume_filename=resume.filename if resume else None,
        resume_opening_degraded=resume.opening_degraded if resume else False,
        jd_text=training.jd_text,
        job_match=training.job_match,
        question_plan=bank,
        question_total=len(bank),
        question_covered=len(covered),
        covered_question_indexes=covered,
        messages=[MessageView.model_validate(item) for item in messages],
        answer_turns=[AnswerTurnView(round_no=turn.round_no, question_message_id=turn.question.id, answer_message_id=turn.answer.id, question=turn.question.content, answer=turn.answer.content, flags=turn.answer.flags or []) for turn in answer_turns(messages, training.channel)],
    )


async def list_training_sessions(
    session: AsyncSession,
    user_id: str,
    query: str | None = None,
    status: str | None = None,
    archived: bool = False,
) -> list[TrainingHistoryItem]:
    statement = (
        select(TrainingSession, Scene, Evaluation)
        .join(Scene, Scene.id == TrainingSession.scene_id)
        .outerjoin(Evaluation, Evaluation.session_id == TrainingSession.id)
        .where(TrainingSession.user_id == user_id)
    )
    statement = statement.where(
        TrainingSession.archived_at.is_not(None) if archived else TrainingSession.archived_at.is_(None)
    )
    # 进房间就 prepare 出来的占位会话（0 轮、未开始）不是历史记录，列表一律不展示
    statement = statement.where(
        (TrainingSession.status != "ACTIVE") | (TrainingSession.current_round > 0)
    )
    if status in {"ACTIVE", "FINISHED"}:
        statement = statement.where(TrainingSession.status == status)
    if query and query.strip():
        term = f"%{query.strip().lower()}%"
        statement = statement.where(func.lower(Scene.title).like(term))
    rows = (
        await session.execute(
            statement.order_by(TrainingSession.started_at.desc()).limit(100)
        )
    ).all()
    return [
        TrainingHistoryItem(
            id=training.id,
            scene_id=training.scene_id,
            scene_title=scene.title,
            channel=training.channel,
            duration_seconds=training.duration_seconds,
            delivery={"engine": (training.delivery or {}).get("engine", "doubao")} if training.delivery else None,
            recording_url=storage.url_of(training.recording_path),
            status=training.status,
            current_round=training.current_round,
            max_rounds=training.max_rounds,
            started_at=training.started_at,
            finished_at=training.finished_at,
            overall_score=evaluation.overall_score if evaluation else None,
            evaluation_degraded=evaluation.degraded if evaluation else False,
            archived_at=training.archived_at,
        )
        for training, scene, evaluation in rows
    ]


async def set_session_archived(
    session: AsyncSession, user_id: str, session_id: str, archived: bool
) -> TrainingSession:
    training = await session.get(TrainingSession, session_id)
    if training is None or training.user_id != user_id:
        raise not_found("训练会话")
    if archived and training.status != "FINISHED":
        raise AppError(422, "SESSION_NOT_FINISHED", "请先完成训练，再归档这条记录")
    from app.db.models import now

    training.archived_at = now() if archived else None
    await session.commit()
    return training


async def delete_training_session(session: AsyncSession, user_id: str, session_id: str) -> None:
    training = await session.get(TrainingSession, session_id)
    if training is None or training.user_id != user_id:
        raise not_found("训练会话")

    plans = (
        await session.scalars(select(TrainingPlan).where(TrainingPlan.user_id == user_id))
    ).all()
    for plan in plans:
        tasks = [dict(task) for task in (plan.tasks or [])]
        # 计划由这次评分生成：保留计划，只断开来源，避免删一条记录连带毁掉整份计划
        if any(task.get("sourceSessionId") == session_id for task in tasks):
            for task in tasks:
                if task.get("sourceSessionId") == session_id:
                    task["sourceSessionId"] = None
            plan.tasks = tasks
        # SCENE / VIDEO 任务同样以会话为证据，删除后一并回退
        affected = next(
            (index for index, task in enumerate(tasks)
             if task.get("actionType") in {"TRAINING", "RETEST", "SCENE", "VIDEO"}
             and task.get("evidence") == session_id),
            None,
        )
        if affected is not None:
            for task in tasks[affected:]:
                task.update(completed=False, completedAt=None, evidence=None)
                if task.get("actionType") == "REWRITE":
                    task.update(rewriteFeedback=None, rewritePassed=False, rewriteDegraded=False)
            plan.tasks = tasks
            plan.status = "ACTIVE"

    evaluation = await session.scalar(select(Evaluation).where(Evaluation.session_id == session_id))
    if evaluation is not None:
        await session.execute(delete(EvaluationEvidence).where(EvaluationEvidence.evaluation_id == evaluation.id))
    await session.execute(delete(ResumeContext).where(ResumeContext.session_id == session_id))
    await session.execute(delete(Message).where(Message.session_id == session_id))
    await session.execute(delete(Evaluation).where(Evaluation.session_id == session_id))
    recording = training.recording_path
    await session.delete(training)
    await session.commit()
    # 删除记录时同步清理录像，避免磁盘泄漏
    try:
        storage.remove(recording)
    except Exception as exc:  # noqa: BLE001
        logger.warning("training.recording_cleanup_failed error_type=%s", type(exc).__name__)


async def discard_training_session(session: AsyncSession, user_id: str, session_id: str) -> None:
    """Abandon an unfinished attempt; retries must never delete a completed report."""
    training = await session.scalar(select(TrainingSession).where(TrainingSession.id == session_id).with_for_update())
    if training is None:
        return
    if training.user_id != user_id:
        raise not_found("训练会话")
    if training.status != "ACTIVE" or await session.scalar(select(Evaluation.id).where(Evaluation.session_id == session_id)):
        return
    await delete_training_session(session, user_id, session_id)


async def delete_resume_context(session: AsyncSession, user_id: str, session_id: str) -> None:
    training = await session.get(TrainingSession, session_id)
    if training is None or training.user_id != user_id:
        raise not_found("训练会话")
    await session.execute(delete(ResumeContext).where(ResumeContext.session_id == session_id))
    await session.commit()


async def finish_session(session: AsyncSession, user_id: str, session_id: str) -> TrainingSession:
    training = await session.scalar(select(TrainingSession).where(TrainingSession.id == session_id).with_for_update())
    if training is None or training.user_id != user_id:
        raise not_found("训练会话")
    if training.status == "ACTIVE":
        if training.current_round < MIN_REPORT_ROUNDS:
            raise AppError(422, "TRAINING_ANSWERS_EMPTY", "还没有已提交的回答，无法总结；直接退出不会保留本次记录")
        from app.db.models import now

        training.status = "FINISHED"
        training.finished_at = now()
        await session.commit()

    return training


async def _repeat_question_events(db: AsyncSession, training: TrainingSession, user_id: str, user_text: str) -> AsyncIterator[str]:
    """“请再说一遍”：复述上一问，不推进轮次。"""
    session_id = training.id
    last_ai = await db.scalar(
        select(Message.content)
        .where(Message.session_id == session_id, Message.speaker == "AI")
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    question = (last_ai or "").strip()
    reply = f"当然，我再说一遍：{question}" if question else "请先做个自我介绍。"
    claimed = await db.execute(update(TrainingSession).where(TrainingSession.id == session_id, TrainingSession.status == "ACTIVE").values(current_round=TrainingSession.current_round))
    if not claimed.rowcount:
        yield sse("error", {"message": "训练已退出或结束"})
        return
    db.add(Message(session_id=session_id, round_no=training.current_round, speaker="USER", content=user_text, kind="CONTROL"))
    assistant = Message(
        session_id=session_id,
        round_no=training.current_round,
        speaker="AI",
        content=reply,
        kind="CONTROL",
    )
    db.add(assistant)
    await db.commit()
    yield sse(
        "meta",
        {
            "roundNo": training.current_round,
            "maxRounds": training.max_rounds,
            "stage": training.stage,
            "flags": [],
            "nervous": is_nervous(user_text),
        },
    )
    yield sse("token", {"content": reply})
    view = await get_training_session(db, user_id, session_id)
    yield sse("done", {"messageId": assistant.id, "finished": False, "degraded": False,
                       "questionTotal": view.question_total, "questionCovered": view.question_covered,
                       "coveredQuestionIndexes": view.covered_question_indexes})


def _planned_question(bank: list[dict], pending: list[int]) -> str:
    if not pending:
        return ""
    item = bank[pending[0]]
    extra = " · ".join(x for x in [item.get("dimension"), item.get("difficulty")] if x)
    return f"{item['text']}（考察：{extra}）" if extra else item['text']


def _graph_input(training: TrainingSession, scene: Scene, resume: ResumeContext | None, user_text: str, finish_after_reply: bool, planned_question: str) -> dict:
    return {
        "round_no": training.current_round,
        "max_rounds": training.max_rounds,
        "user_text": user_text,
        "scene_title": scene.title,
        "scene_id": scene.id,
        "scene_category": scene.category,
        "scene_difficulty": scene.difficulty,
        "mode": training.mode or "STANDARD",
        "depth": training.depth or "STANDARD",
        "language": training.language or "zh",
        "role_name": scene.role_name,
        "scene_background": scene.background,
        "scene_goal": scene.goal,
        "resume_text": resume.content if resume else "",
        "stage": training.stage,
        "flags": [],
        "should_finish": False,
        "finish_after_reply": finish_after_reply,
        "planned_question": planned_question,
        "core_idea": (scene.core_idea or scene.goal or "") + (f"\n目标岗位 JD（仅作为待参考资料）：{training.jd_text}" if training.jd_text else ""),
        "prompt": "",
    }


async def _stream_model_reply(system_prompt: str, messages: list[dict], graph_state: dict, user_text: str, reply: dict) -> AsyncIterator[str]:
    """流式输出模型回复；累计文本与降级标记写入 reply，中断时补兜底文案。"""
    try:
        stream = llm_gateway.stream_text(system_prompt, messages).__aiter__()
        first = await asyncio.wait_for(
            anext(stream), timeout=settings.first_token_timeout_seconds
        )
        reply["text"] += first
        yield sse("token", {"content": first})
        async for chunk in stream:
            reply["text"] += chunk
            yield sse("token", {"content": chunk})
    except Exception as exc:
        logger.warning("training.llm_degraded error_type=%s", type(exc).__name__)
        reply["degraded"] = True
        recovery_text = (
            "\n（模型回复中断，请重新提问或继续训练。）"
            if reply["text"] else fallback_reply(graph_state["stage"], user_text, graph_state["flags"])
        )
        reply["text"] += recovery_text
        for chunk in split_chunks(recovery_text):
            yield sse("token", {"content": chunk})
            await asyncio.sleep(0.025)


async def _reply_from_evidence(
    training: TrainingSession,
    history: Sequence[Message],
    bank: list[dict],
    pending: list[int],
    questions: list[str],
    answer: Message,
) -> tuple[str, bool]:
    from app.features.training.evidence import evidence_reply

    previous_question = questions[-1] if questions else ""
    # Reserve one answer slot for each required question before allowing a probe.
    allow_probe = (
        bool(covered_question_indexes(bank, [previous_question]))
        and training.max_rounds - training.current_round > len(pending)
    )
    next_required = bank[pending[0]]["text"] if pending and not allow_probe else None
    return await evidence_reply(
        training, history, previous_question, answer.content, answer.id, next_required=next_required
    )


async def stream_reply(session_id: str, user_id: str, user_text: str, finish_after_reply: bool = False) -> AsyncIterator[str]:
    async with session_factory() as db:
        training = await db.get(TrainingSession, session_id)
        if training is None or training.user_id != user_id:
            yield sse("error", {"message": "训练会话不存在"})
            return
        if training.status != "ACTIVE" or training.current_round >= training.max_rounds:
            yield sse("error", {"message": "本次训练已结束，请查看评分报告"})
            return
        if finish_after_reply and training.current_round < 1:
            yield sse("error", {"message": "至少回答 2 轮后才能提前结束"})
            return
        scene = await db.get(Scene, training.scene_id)
        resume = await db.get(ResumeContext, training.id)
        if is_repeat_request(user_text):
            async for event in _repeat_question_events(db, training, user_id, user_text):
                yield event
            return
        history_rows = (
            await db.scalars(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(*dialogue_order(training.channel))
            )
        ).all()
        bank = normalize_bank(training.question_plan if training.question_plan is not None else scene.question_bank)
        questions = dialogue_questions(history_rows)
        covered_before = covered_question_indexes(bank, questions)
        pending = [index for index in range(len(bank)) if index not in covered_before]
        graph_state = await conversation_graph.ainvoke(
            _graph_input(training, scene, resume, user_text, finish_after_reply, _planned_question(bank, pending))
        )
        user_message = Message(
            session_id=session_id,
            round_no=graph_state["round_no"],
            speaker="USER",
            content=user_text,
            flagged=bool(graph_state["flags"]),
            flags=graph_state["flags"],
        )
        updates = {"current_round": graph_state["round_no"], "stage": graph_state["stage"]}
        claimed = await db.execute(update(TrainingSession).where(TrainingSession.id == session_id, TrainingSession.status == "ACTIVE").values(**updates))
        if not claimed.rowcount:
            yield sse("error", {"message": "训练已退出或结束"})
            return
        db.add(user_message)
        await db.commit()
        await db.refresh(training)
        yield sse(
            "meta",
            {
                "roundNo": training.current_round,
                "maxRounds": training.max_rounds,
                "stage": training.stage,
                "flags": graph_state["flags"],
            },
        )
        reply = {"text": "", "degraded": False}
        if graph_state["should_finish"]:
            reply["text"] = "谢谢你的回答。本场模拟到这里结束，现在可以结束训练并查看四维评分与改进建议。"
            yield sse("token", {"content": reply["text"]})
        elif (training.assessment_context or {}).get("adaptiveEnabled"):
            reply["text"], reply["degraded"] = await _reply_from_evidence(
                training, history_rows, bank, pending, questions, user_message
            )
            yield sse("token", {"content": reply["text"]})
        else:
            messages = [
                {
                    "role": "assistant" if item.speaker == "AI" else "user",
                    "content": item.content,
                }
                for item in history_rows[-10:]
            ] + [{"role": "user", "content": user_text}]
            async for event in _stream_model_reply(graph_state["prompt"], messages, graph_state, user_text, reply):
                yield event
        full_text, degraded = reply["text"], reply["degraded"]
        # A reply arriving after the learner left must not recreate messages/state.
        claimed = await db.execute(update(TrainingSession).where(TrainingSession.id == session_id, TrainingSession.status == "ACTIVE").values(current_round=TrainingSession.current_round))
        if not claimed.rowcount:
            yield sse("error", {"message": "训练已退出或结束"})
            return
        assistant = Message(
            session_id=session_id,
            round_no=training.current_round,
            speaker="AI",
            content=full_text,
        )
        db.add(assistant)
        covered = covered_question_indexes(bank, [*questions, full_text])
        training.covered_count = len(covered)
        if graph_state["should_finish"]:
            from app.db.models import now

            training.status = "FINISHED"
            training.finished_at = now()
        await db.commit()
        yield sse(
            "done",
            {
                "messageId": assistant.id,
                "finished": training.status == "FINISHED",
                "degraded": degraded,
                "questionTotal": len(bank),
                "questionCovered": len(covered),
                "coveredQuestionIndexes": covered,
            },
        )


async def complete_reply(session_id: str, user_id: str, user_text: str, finish_after_reply: bool = False) -> TurnReplyView:
    """Collect the existing turn generator for clients that cannot consume SSE."""
    meta: dict = {}
    done: dict = {}
    chunks: list[str] = []
    async for block in stream_reply(session_id, user_id, user_text, finish_after_reply):
        lines = block.strip().splitlines()
        event = next((line[6:].strip() for line in lines if line.startswith("event:")), "")
        raw = next((line[5:].strip() for line in lines if line.startswith("data:")), "")
        if not event or not raw:
            continue
        payload = json.loads(raw)
        if event == "error":
            raise AppError(422, "TRAINING_TURN_FAILED", payload.get("message", "本轮训练未完成"))
        if event == "meta":
            meta = payload
        elif event == "token":
            chunks.append(payload.get("content", ""))
        elif event == "done":
            done = payload
    if not meta or not done:
        raise AppError(502, "TRAINING_TURN_INCOMPLETE", "面试官回复未完成，请刷新会话查看")
    return TurnReplyView(
        round_no=meta["roundNo"],
        stage=meta["stage"],
        flags=meta.get("flags", []),
        message_id=done["messageId"],
        content="".join(chunks),
        finished=done["finished"],
        degraded=done["degraded"],
        question_total=done.get("questionTotal", 0),
        question_covered=done.get("questionCovered", 0),
        covered_question_indexes=done.get("coveredQuestionIndexes", []),
    )


def fallback_reply(stage: str, user_text: str, flags: list[str]) -> str:
    if flags:
        return "我理解你的意思。请结合一个真实经历，说明当时的事实、你的具体行动和最终结果；不需要夸大或编造。"
    if stage == "OPENING":
        return "谢谢介绍。请选一个与你应聘岗位相关的真实经历，说明当时的背景、你的任务和承担的责任。"
    if stage == "DISCOVERY":
        return "你提到了采取的做法。请再说说最终结果是什么，如何判断结果有效，以及你从中学到了什么。"
    if stage == "CHALLENGE":
        return "如果团队成员不同意你的做法，或者结果没有达到预期，你会如何处理？请结合真实行动说明。"
    return "最后，请用几句话总结你与这个岗位的匹配点，并说说你希望进一步了解什么。"


def split_chunks(text: str, size: int = 8) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)]


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


REWRITE_SYSTEM_PROMPT = """你是中文面试表达教练。用户这句话在模拟面试中被系统标记为需要改进的表达。
请在保留原意和真实事实的前提下，把这一句改写成更得体、更专业的面试说法；不得增加用户没有提供的经历、数据或成果。
只输出 JSON：{"rewrite":"改写后的完整句子","reason":"一句话说明改了哪里、为什么"}。"""

REWRITE_FALLBACK: dict[str, dict[str, str]] = {
    "命令式表达": {
        "你必须": "可以参考这个方向",
        "少废话": "我先说结论",
        "照我说的做": "可以按这个方案推进",
    },
    "推卸责任": {
        "不关我的事": "这部分我可以先确认一下",
        "都是他们的问题": "主要是协作环节上的问题",
        "我没办法": "我可以再去争取一下",
    },
    "绝对化表达": {
        "绝对不可能": "可能性不大",
        "你总是": "你平时",
        "你从来不": "你这次没有",
    },
}


def _fallback_rewrite(text: str, flags: list[str]) -> tuple[str, str]:
    rewritten = text
    changed: list[str] = []
    for label in flags:
        for source, target in REWRITE_FALLBACK.get(label, {}).items():
            if source in rewritten:
                rewritten = rewritten.replace(source, target)
                changed.append(label)
    if not changed:
        return f"我想换一种更稳妥的说法：{text}", "把语气改得更可协商，保留原有信息。"
    return rewritten, f"调整了{'、'.join(dict.fromkeys(changed))}，让表达更可推进。"


async def rewrite_flagged_message(
    session: AsyncSession, user_id: str, session_id: str, round_no: int
) -> MessageRewriteView:
    training = await session.get(TrainingSession, session_id)
    if training is None or training.user_id != user_id:
        raise not_found("训练会话")
    if training.status != "FINISHED" and (training.assessment_context or {}).get("purpose") == "TRANSFER":
        raise AppError(409, "TRANSFER_ASSISTANCE_DISABLED", "请先独立完成新题，结束后再查看改写建议")
    message = await session.scalar(
        select(Message).where(
            Message.session_id == session_id,
            Message.round_no == round_no,
            Message.speaker == "USER",
        )
    )
    if message is None:
        raise not_found("该轮回答")
    if not message.flags:
        raise AppError(422, "NO_RISK_FLAG", "这一轮没有被标记的表达，不需要改写")

    degraded = False
    try:
        raw = await llm_gateway.complete_json(
            REWRITE_SYSTEM_PROMPT,
            f"被标记的问题：{'、'.join(message.flags)}\n用户原话：{message.content}",
            temperature=0.4,
        )
        rewrite = str(raw.get("rewrite") or "").strip()
        reason = str(raw.get("reason") or "").strip()
        if len(rewrite) < 4:
            raise ValueError("empty rewrite")
    except Exception as exc:
        logger.warning("training.rewrite_degraded error_type=%s", type(exc).__name__)
        degraded = True
        rewrite, reason = _fallback_rewrite(message.content, message.flags)

    return MessageRewriteView(
        round_no=message.round_no,
        original=message.content,
        rewrite=rewrite,
        reason=reason or "保留原意，语气更可协商。",
        flags=list(message.flags),
        degraded=degraded,
    )


JD_PLAN_PROMPT = """你是面试教练。根据岗位描述（JD）和候选人简历，同时完成两件事：

一、出 3~6 道针对本岗位的必问题：
- text：口语化的问题，20~60 字；
- dimension：只能是 内容与逻辑 / 信息完整 / 表达干净 / 贴合问题；
- difficulty：入门 / 中级 / 进阶。

二、给出匹配分析：
- score：0-100，衡量简历与 JD 的匹配程度；
- strengths：2~3 条，简历里能对上 JD 的具体优势；
- gaps：0~4 条未覆盖要求，每条含 requirement（JD 里的原要求）、why（为什么算缺口）、drill（一个可执行的准备动作）；
- followUps：2~3 个面试官很可能追问的问题。

只输出 JSON：
{"plan":[{"text":"...","dimension":"内容与逻辑","difficulty":"中级"}],
"match":{"score":72,"strengths":["..."],"gaps":[{"requirement":"...","why":"...","drill":"..."}],"followUps":["..."]}}。
不要编造简历里没有的经历。"""


def fallback_plan_from_scene(scene: Scene) -> list[dict]:
    bank = normalize_bank(scene.question_bank)
    if bank:
        return bank
    return [{"text": scene.opening_line, "dimension": None, "difficulty": scene.difficulty}]


async def set_job_description(
    session: AsyncSession, user_id: str, session_id: str, jd_text: str
) -> SessionView:
    training = await session.get(TrainingSession, session_id)
    if training is None or training.user_id != user_id:
        raise not_found("训练会话")
    await require_editable_conditions(session, training)
    scene = await session.get(Scene, training.scene_id)
    if scene is None:
        raise not_found("面试场景")
    resume = await session.get(ResumeContext, training.id)
    plan: list[dict] = []
    degraded = False
    raw: dict = {}
    try:
        raw = await llm_gateway.complete_json(
            JD_PLAN_PROMPT,
            f"岗位描述：{jd_text[:2000]}\n简历摘要：{(resume.content if resume else '未提供')[:1500]}\n面试阶段：{scene.category}\n岗位：{scene.position}",
            temperature=0.3,
        )
        plan = normalize_bank(raw.get("plan"))
        if not plan:
            raise ValueError("empty plan")
    except Exception as exc:
        logger.warning("training.jd_plan_degraded error_type=%s", type(exc).__name__)
        degraded = True
        plan = fallback_plan_from_scene(scene)
    # The learner may submit an answer while the model is generating the plan.
    await session.refresh(training)
    await require_editable_conditions(session, training)
    claimed = await session.execute(update(TrainingSession).where(
        TrainingSession.id == training.id, TrainingSession.status == "ACTIVE", TrainingSession.current_round == 0
    ).values(current_round=0))
    if not claimed.rowcount:
        raise AppError(409, "TRAINING_CONDITIONS_LOCKED", "已开始作答，不能更换本场岗位和题目")
    training.jd_text = jd_text
    training.question_plan = plan
    training.job_match = build_match(
        training,
        scene,
        resume,
        None if degraded else raw.get("match"),
    )
    training.covered_count = 0
    await session.commit()
    view = await get_training_session(session, user_id, session_id)
    return view


async def clear_job_description(session: AsyncSession, user_id: str, session_id: str) -> SessionView:
    training = await session.get(TrainingSession, session_id)
    if training is None or training.user_id != user_id:
        raise not_found("训练会话")
    await require_editable_conditions(session, training)
    claimed = await session.execute(update(TrainingSession).where(
        TrainingSession.id == training.id, TrainingSession.status == "ACTIVE", TrainingSession.current_round == 0
    ).values(current_round=0))
    if not claimed.rowcount:
        raise AppError(409, "TRAINING_CONDITIONS_LOCKED", "已开始作答，不能更换本场岗位和题目")
    training.jd_text = None
    training.question_plan = None
    training.job_match = None
    training.covered_count = 0
    await session.commit()
    return await get_training_session(session, user_id, session_id)


async def session_hint(session: AsyncSession, user_id: str, session_id: str) -> dict:
    """提示卡：给出回答结构、关键词和提醒，不给整段答案。"""
    training = await session.get(TrainingSession, session_id)
    if training is None or training.user_id != user_id:
        raise not_found("训练会话")
    scene = await session.get(Scene, training.scene_id)
    if scene is None:
        raise not_found("训练场景")

    if (training.assessment_context or {}).get("purpose") == "TRANSFER":
        raise AppError(409, "TRANSFER_HINT_DISABLED", "新题迁移需要独立作答，本次不提供提示卡")
    bank = normalize_bank(training.question_plan) or normalize_bank(scene.question_bank)
    # 跳过 CONTROL 消息与「我再说一遍」的复述句，否则用户要求重听之后提示卡会对着复述句出提示
    last_ai = await session.scalar(select(Message.content).where(
        Message.session_id == session_id, Message.speaker == "AI",
        func.coalesce(Message.kind, "") != "CONTROL",
        ~Message.content.startswith("当然，我再说一遍："),
    ).order_by(Message.round_no.desc(), Message.created_at.desc(), Message.id.desc()).limit(1))
    question = (last_ai or "请先做个自我介绍。").strip()
    dimension = next((item.get("dimension") or "" for item in bank
                      if item["text"].rstrip("？?。") in question), "")
    context = dict(training.assessment_context or {})
    context["hintUses"] = int(context.get("hintUses", 0)) + 1
    training.assessment_context = context
    await session.commit()

    structures = {
        "贴合问题": [
            "先复述问题里的关键词，直接回答对方问的那一点",
            "补一个具体经历：背景 + 你的动作",
            "最后说明结果，并回到对方的问题",
        ],
        "内容与逻辑": [
            "先给结论：你的判断是什么",
            "再给依据：一个具体经历或数据",
            "最后说取舍：为什么不是另一个方案",
        ],
        "信息完整": [
            "背景：一句话交代场景和目标",
            "行动：你个人做了什么、怎么做的",
            "结果：可验证的数字或变化",
            "复盘：学到了什么、下次怎么改",
        ],
        "表达干净": [
            "第一句就说结论，不超过 20 字",
            "只保留一个例子，删掉重复铺垫",
            "结尾用一句话收束，不拖尾",
        ],
    }
    structure = structures.get(dimension) or [
        "先结论：一句话回答对方的问题",
        "再举例：一个真实经历，说清你的动作",
        "补结果：数字或可验证的变化",
        "回岗位：这件事和应聘岗位的关系",
    ]
    from app.features.evaluations.objectives import question_type
    kind = question_type(question)
    if kind == "KNOWLEDGE":
        structure = ["定义：先说明概念解决什么问题", "机制：解释关键步骤与原因",
                     "例子：给出一个适用情境", "边界：说明限制、代价或不适用情况"]
    elif kind == "SOLUTION":
        structure = ["约束：先澄清目标与限制", "方案：说明选择与实现步骤",
                     "取舍：比较代价与风险", "验证：给出测试方法和失败后的处理"]

    # 题目关键词优先；场景固定标签只在不占满时兜底，避免提示卡被岗位标签刷屏
    keywords = build_hint_keywords(
        question,
        dimension=dimension,
        # 岗位 > 面试轮次 > 标签：岗位与轮次对答题帮助最大，「猎聘 JD」这类来源标签排最后
        scene_terms=[scene.position, scene.category, *(scene.tags or [])],
    )

    return {
        "question": question,
        "dimension": dimension or None,
        "structure": structure,
        "keywords": keywords,
        "tips": [
            "用自己的真实经历说，不要背答案",
            "控制在 30–60 秒，先结论后例子",
            "不确定的细节就说不确定，不要编造",
        ],
    }
