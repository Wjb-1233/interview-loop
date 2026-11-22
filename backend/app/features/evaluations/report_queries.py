"""Read-only report projection and revision snapshots."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Evaluation, EvaluationEvidence, Message, ResumeContext, TrainingPlan, TrainingSession
from app.features.evaluations import objectives
from app.features.evaluations.schemas import DimensionScores, EvidenceView, EvaluationView
from app.features.evaluations.scoring import speech_statistics
from app.features.evaluations.quality import earlier_training, formal_filters, quality, training_order, verified_rows
from app.features.training.answer_turns import answer_turns
from app.features.training.message_order import dialogue_order
from app.features.training.comparison_conditions import condition_filters


SCORE_UNAVAILABLE_REASON = "本场专业核查与四维评分矛盾，分数暂不可用，请重新作答或重评"


def score_unavailable_reason(evaluation: Evaluation) -> str | None:
    """矛盾未消解时分数会误导：只在读取层置空，库里的历史值不动。"""
    return SCORE_UNAVAILABLE_REASON if evaluation.review_required else None


async def to_view(session: AsyncSession, evaluation: Evaluation) -> EvaluationView:
    current_session = await session.get(TrainingSession, evaluation.session_id)
    evidence_rows = (await session.scalars(
        select(EvaluationEvidence).where(EvaluationEvidence.evaluation_id == evaluation.id)
    )).all()
    messages = (await session.scalars(
        select(Message).where(Message.session_id == evaluation.session_id).order_by(*dialogue_order(current_session.channel))
    )).all()
    by_id = {message.id: message for message in messages}
    evidence = [
        EvidenceView(
            dimension=row.dimension,
            round_no=row.round_no,
            question_message_id=row.question_message_id,
            answer_message_id=row.answer_message_id,
            question=by_id[row.question_message_id].content,
            answer=by_id[row.answer_message_id].content,
            quote=row.quote,
            reason=row.reason,
            next_action=row.next_action,
            resume_quote=row.resume_quote,
        )
        for row in verified_rows(evidence_rows, messages, current_session)
    ]
    plans = (await session.scalars(
        select(TrainingPlan).where(TrainingPlan.user_id == evaluation.user_id)
    )).all()
    plan = next((item for item in plans if any(
        task.get("sourceSessionId") == evaluation.session_id for task in (item.tasks or [])
    )), None)
    report_quality = quality(evaluation, current_session, evidence)
    unavailable_reason = score_unavailable_reason(evaluation)
    current_resume = await session.get(ResumeContext, evaluation.session_id)
    question_types = [{'roundNo': turn.round_no, 'type': objectives.question_type(turn.question.content)}
                      for turn in answer_turns(messages, current_session.channel)]
    # 比较场景、方式、强度、语言及相同简历/JD。
    previous = await session.scalar(
        select(Evaluation)
        .join(TrainingSession, TrainingSession.id == Evaluation.session_id)
        .outerjoin(ResumeContext, ResumeContext.session_id == TrainingSession.id)
        .where(
            *condition_filters(current_session, current_resume.content if current_resume else None),
            Evaluation.user_id == evaluation.user_id,
            TrainingSession.user_id == evaluation.user_id,
            Evaluation.id != evaluation.id,
            earlier_training(current_session),
            *formal_filters(),
        )
        .order_by(*training_order())
        .limit(1)
    )
    return EvaluationView(
        id=evaluation.id,
        session_id=evaluation.session_id,
        scores=DimensionScores(
            logic=evaluation.logic_score,
            appropriateness=evaluation.appropriateness_score,
            correctness=evaluation.correctness_score,
            relevance=evaluation.relevance_score,
            concision=evaluation.concision_score,
        ),
        overall_score=None if unavailable_reason else evaluation.overall_score,
        score_unavailable_reason=unavailable_reason,
        risk_flags=evaluation.risk_flags or [],
        summary=evaluation.summary,
        suggestions=evaluation.suggestions,
        style_tags=evaluation.style_tags,
        created_at=evaluation.created_at,
        degraded=evaluation.degraded,
        **report_quality,
        revision=len(evaluation.revision_history or []) + 1,
        revision_history=evaluation.revision_history or [],
        evidence=evidence,
        plan_id=current_session.plan_id or (plan.id if plan else None),
        speech_stats={**(evaluation.speech_stats or {}), **speech_statistics(messages, current_session.channel)},
        assessment=evaluation.assessment,
        technical_checks=(evaluation.speech_stats or {}).get("technicalChecks", []),
        question_types=question_types,
        reference=evaluation.reference_text,
        upgrades=evaluation.upgrades or [],
        stability=evaluation.stability,
        previous_scores=DimensionScores(
            logic=previous.logic_score,
            appropriateness=previous.appropriateness_score,
            correctness=previous.correctness_score,
            relevance=previous.relevance_score,
            concision=previous.concision_score,
        ) if previous and report_quality["eligible_for_growth"] else None,
        previous_overall=previous.overall_score if previous and report_quality["eligible_for_growth"] else None,
    )



async def evaluation_snapshot(session: AsyncSession, evaluation: Evaluation, training: TrainingSession) -> dict:
    """Freeze the old text and evidence before transcript edits or a successful regrade."""
    view = await to_view(session, evaluation)
    snapshot = view.model_dump(mode="json", by_alias=True, exclude={"revision_history", "previous_scores", "previous_overall"})
    # 历史版本冻结的是当时的库内分数，即使读取层把它标成不可用。
    snapshot["overallScore"] = evaluation.overall_score
    snapshot.pop("scoreUnavailableReason", None)
    return snapshot

