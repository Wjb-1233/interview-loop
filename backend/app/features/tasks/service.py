"""Read-only access to results produced by the retired video analysis worker."""
from app.db.base import session_factory
from app.db.models import AnalysisTask

async def get_task(user_id: str, task_id: str) -> AnalysisTask | None:
    async with session_factory() as session:
        task = await session.get(AnalysisTask, task_id)
        return task if task is not None and task.user_id == user_id else None
