from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import ok
from app.core.security import CurrentUser
from app.db.base import get_session
from app.features.plans.schemas import CompleteTaskRequest, PracticeRequest
from app.features.evaluations.service import regenerate_training_plan
from app.features.plans.lesson_videos import get_job_state, get_lesson_video, start_lesson_video
from app.features.plans.service import (
    personalized_lesson,
    complete_course_task,
    complete_lesson_step,
    complete_training_task,
    get_training_plan,
    list_training_plans,
    submit_lesson_practice,
)

router = APIRouter(prefix="/training-plans", tags=["训练计划"])
DbSession = Annotated[AsyncSession, Depends(get_session)]


class RegeneratePlanRequest(BaseModel):
    dimension: str = Field(min_length=2, max_length=10)


@router.post("/regenerate", status_code=201)
async def regenerate(body: RegeneratePlanRequest, user: CurrentUser, session: DbSession) -> dict:
    plan_id = await regenerate_training_plan(session, user.id, body.dimension)
    return ok({"id": plan_id})


class LessonRequest(BaseModel):
    task_key: str = Field(default="course", min_length=1, max_length=40)
    force: bool = False
    engine: str = Field(default="auto", pattern="^(auto|python|remotion)$")


@router.post("/{plan_id}/transfer", status_code=201)
async def begin_transfer(plan_id: str, user: CurrentUser, session: DbSession) -> dict:
    from app.features.auth.email_verify import require_verified
    from app.features.plans.transfer import start_transfer
    require_verified(user)
    return ok({"id": await start_transfer(session, user.id, plan_id)})


@router.post("/{plan_id}/lesson")
async def lesson(plan_id: str, body: LessonRequest, user: CurrentUser, session: DbSession) -> dict:
    result = await personalized_lesson(session, user.id, plan_id, body.task_key, force=body.force)
    return ok(result)


@router.post("/{plan_id}/lesson/video")
async def lesson_video(plan_id: str, body: LessonRequest, user: CurrentUser, session: DbSession) -> dict:
    """秒回：有成片直接返回，否则入队由后台 worker 渲染。"""
    return ok(await start_lesson_video(session, user.id, plan_id, body.task_key, body.engine, body.force))


@router.get("/{plan_id}/lesson/video/state")
async def lesson_video_job_state(
    plan_id: str,
    user: CurrentUser,
    session: DbSession,
    task_key: str = "course",
    engine: Literal["auto", "python", "remotion"] = "auto",
) -> dict:
    """轮询渲染进度：排队/渲染中/完成/失败都在这里。"""
    return ok(await get_job_state(session, user.id, plan_id, task_key, engine))


@router.get("/{plan_id}/lesson/video")
async def lesson_video_state(
    plan_id: str,
    user: CurrentUser,
    session: DbSession,
    task_key: str = "course",
    engine: Literal["auto", "python", "remotion"] = "auto",
) -> dict:
    return ok(await get_lesson_video(session, user.id, plan_id, task_key, engine))


@router.get("")
async def list_all(user: CurrentUser, session: DbSession) -> dict:
    plans = await list_training_plans(session, user.id)
    return ok([item.model_dump(by_alias=True) for item in plans])


@router.get("/{plan_id}")
async def get_one(plan_id: str, user: CurrentUser, session: DbSession) -> dict:
    plan = await get_training_plan(session, user.id, plan_id)
    return ok(plan.model_dump(by_alias=True))


@router.post("/{plan_id}/tasks/{task_key}/complete")
async def complete_task(
    plan_id: str,
    task_key: str,
    body: CompleteTaskRequest,
    user: CurrentUser,
    session: DbSession,
) -> dict:
    plan = await complete_training_task(session, user.id, plan_id, task_key, body.evidence)
    return ok(plan.model_dump(by_alias=True))


@router.post("/{plan_id}/tasks/{task_key}/course/complete")
async def complete_course(plan_id: str, task_key: str, user: CurrentUser, session: DbSession) -> dict:
    plan = await complete_course_task(session, user.id, plan_id, task_key)
    return ok(plan.model_dump(by_alias=True))


@router.post("/{plan_id}/tasks/{task_key}/steps/{step_index}/complete")
async def complete_step(
    plan_id: str, task_key: str, step_index: int, user: CurrentUser, session: DbSession
) -> dict:
    plan = await complete_lesson_step(session, user.id, plan_id, task_key, step_index)
    return ok(plan.model_dump(by_alias=True))


@router.post("/{plan_id}/tasks/{task_key}/practice")
async def submit_practice(
    plan_id: str,
    task_key: str,
    body: PracticeRequest,
    user: CurrentUser,
    session: DbSession,
) -> dict:
    plan = await submit_lesson_practice(session, user.id, plan_id, task_key, body.answer)
    return ok(plan.model_dump(by_alias=True))
