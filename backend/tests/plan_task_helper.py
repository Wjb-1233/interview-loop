"""测试辅助：给新计划注入一个可训练任务（产品已不再自动生成复练任务）。"""

import asyncio

from app.db.base import session_factory
from app.db.models import TrainingPlan


def add_scene_task(plan_id: str, scene_id: str, key: str = "manual-retry") -> str:
    async def insert():
        async with session_factory() as session:
            plan = await session.get(TrainingPlan, plan_id)
            assert plan is not None
            tasks = list(plan.tasks or [])
            tasks.insert(0, {
            "key": key,
            "day": 1,
            "task": "手动注入的训练任务",
            "actionType": "SCENE",
            "sceneId": scene_id,
            "completed": False,
            "completedAt": None,
            "evidence": None,
            })
            plan.tasks = tasks
            await session.commit()
    asyncio.run(insert())
    return key
