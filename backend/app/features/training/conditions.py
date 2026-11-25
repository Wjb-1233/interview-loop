"""One edit policy shared by the API and the interview settings UI."""
from app.core.errors import AppError
from app.db.models import TrainingPlan


async def conditions_locked_reason(session, training) -> str | None:
    if training.status != "ACTIVE":
        return "本场面试已结束，岗位和题目已固定；如需调整，请开始新的训练。"
    if (training.assessment_context or {}).get("purpose") == "TRANSFER":
        return "新题迁移需要独立完成本组题目，不能更换岗位和题目。"
    if training.plan_id and training.task_key:
        plan = await session.get(TrainingPlan, training.plan_id)
        task = next((item for item in (plan.tasks if plan else []) or [] if item.get("key") == training.task_key), None)
        if task and task.get("actionType") == "RETEST":
            return "同条件复测沿用原训练的岗位和题目，不能在本场更换。"
    if training.current_round > 0:
        return "已开始作答，岗位和题目已固定；如需调整，请开始新的训练。"
    return None


async def require_editable_conditions(session, training):
    reason = await conditions_locked_reason(session, training)
    if reason:
        raise AppError(409, "TRAINING_CONDITIONS_LOCKED", reason)
