"""Shared evidence requirements for reports and formal growth comparisons."""
from sqlalchemy import LargeBinary, and_, case, cast, exists, func, select
from sqlalchemy.orm import aliased

from app.db.models import Evaluation, EvaluationEvidence, Message, TrainingSession
from app.features.training.answer_turns import answer_turns, question_offset
from app.features.training.message_order import first_message_in_round
from app.features.training.policy import MIN_GROWTH_ROUNDS

DIMENSIONS = ("logic", "relevance", "correctness", "concision")


def verified_rows(rows, messages, training):
    by_id = {message.id: message for message in messages}
    turns = {turn.round_no: turn for turn in answer_turns(messages, training.channel)}
    return [row for row in rows if (
        row.dimension in DIMENSIONS
        and (question := by_id.get(row.question_message_id)) is not None
        and (answer := by_id.get(row.answer_message_id)) is not None
        and question.speaker == "AI" and answer.speaker == "USER"
        and (turn := turns.get(row.round_no)) is not None
        and turn.question.id == question.id and turn.answer.id == answer.id
        and answer.round_no == row.round_no
        and row.quote and row.quote.strip() and row.quote in answer.content
        and row.reason.strip() and row.next_action.strip()
    )]


def quality(evaluation, training, evidence):
    missing = [key for key in DIMENSIONS if key not in {row.dimension for row in evidence}]
    if (training.delivery or {}).get("rescoreRequired"):
        status = "PENDING_RESCORE"
    elif evaluation.review_required:
        status = "REVIEW_REQUIRED"
    elif evaluation.degraded:
        status = "RULE_BASED"
    elif training.current_round < MIN_GROWTH_ROUNDS:
        status = "LIMITED_SAMPLE"
    elif missing:
        status = "INSUFFICIENT_EVIDENCE"
    else:
        status = "VERIFIED"
    eligible = status == "VERIFIED" and training.status == "FINISHED" and training.language == "zh" and (training.assessment_context or {}).get("purpose") != "TRANSFER"
    return {"quality_status": status, "missing_evidence_dimensions": missing, "eligible_for_growth": eligible, "answered_rounds": training.current_round}


def formal_filters():
    """SQL equivalent of quality(), including exact, case-sensitive quote matching."""
    filters = [Evaluation.degraded.is_(False), TrainingSession.status == "FINISHED",
               Evaluation.review_required.is_(False),
               func.coalesce(TrainingSession.assessment_context["purpose"].as_string(), "PRACTICE") != "TRANSFER",
               TrainingSession.current_round >= MIN_GROWTH_ROUNDS,
               TrainingSession.language == "zh",
               TrainingSession.delivery["rescoreRequired"].as_boolean().is_not(True)]
    for dimension in DIMENSIONS:
        question, answer = aliased(Message), aliased(Message)
        filters.append(exists(select(1).select_from(EvaluationEvidence)
            .join(question, question.id == EvaluationEvidence.question_message_id)
            .join(answer, answer.id == EvaluationEvidence.answer_message_id)
            .where(
                EvaluationEvidence.evaluation_id == Evaluation.id,
                EvaluationEvidence.dimension == dimension,
                question.session_id == TrainingSession.id, answer.session_id == TrainingSession.id,
                question.speaker == "AI", answer.speaker == "USER",
                first_message_in_round(question), first_message_in_round(answer),
                answer.round_no == EvaluationEvidence.round_no,
                question.round_no == EvaluationEvidence.round_no - case((TrainingSession.channel == "TEXT", question_offset("TEXT")), else_=question_offset("VOICE")),
                func.length(func.trim(EvaluationEvidence.quote)) > 0,
                func.length(func.trim(EvaluationEvidence.reason)) > 0,
                func.length(func.trim(EvaluationEvidence.next_action)) > 0,
                func.instr(cast(answer.content, LargeBinary), cast(EvaluationEvidence.quote, LargeBinary)) > 0,
            ).correlate(Evaluation, TrainingSession)))
    return filters


def training_order():
    return (func.coalesce(TrainingSession.finished_at, TrainingSession.started_at).desc(),
            TrainingSession.started_at.desc(), TrainingSession.id.desc())


def earlier_training(training):
    # A stable lexicographic order independent of when a report was (re)graded.
    from sqlalchemy import or_
    ended = func.coalesce(TrainingSession.finished_at, TrainingSession.started_at)
    current_end = training.finished_at or training.started_at
    return or_(ended < current_end,
               and_(ended == current_end, TrainingSession.started_at < training.started_at),
               and_(ended == current_end, TrainingSession.started_at == training.started_at,
                    TrainingSession.id < training.id))
