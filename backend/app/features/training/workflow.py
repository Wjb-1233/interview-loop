"""Application use case for ending a training attempt.

The finished attempt is committed before model I/O. Report retries retain its ID;
plan creation and first-result skill updates remain conditional in evaluation.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import AppError
from app.features.training.service import finish_session
from app.features.evaluations.service import evaluate_session
from app.features.evaluations.schemas import EvaluationView


async def end_training_attempt(
    db: AsyncSession, user_id: str, session_id: str, create_plan: bool = True
) -> EvaluationView:
    training = await finish_session(db, user_id, session_id)
    report = await evaluate_session(db, user_id, session_id, create_plan=create_plan)
    if training.plan_id and training.task_key and (training.assessment_context or {}).get("purpose") != "TRANSFER":
        from app.features.plans.service import complete_training_task
        try:
            await complete_training_task(db, user_id, training.plan_id, training.task_key, training.id)
        except AppError:
            # A partial interview can have a report without completing its plan task.
            pass
    return report
