"""把微课视频与计划中的固定课程关联，并兼容已有视频文件。"""

import asyncio
import copy
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.errors import AppError, not_found
from app.db.models import LessonVideoJob, TrainingPlan
from app.features.lessons import video as renderer
from app.features.plans.service import personalized_lesson

logger = logging.getLogger(__name__)

QUEUED_STAGE = "排队"
DRAFT_STAGE = "备稿"
NARRATION_STAGE = "旁白合成"
RENDER_STAGE = "渲染"
DONE_STAGE = "完成"
FAILED_STAGE = "失败"
# 契约里没有 force 列：入队时把「本次强制重渲染」写进 stage，worker 认领时读出来再改回排队态
FORCE_STAGE = "重新生成"
JOB_POLL_SECONDS = 3
JOB_STALE_SECONDS = 600
# 看门狗阈值比渲染硬超时多一点余量，避免和正在跑的任务抢判
STALE_GRACE_SECONDS = 60

Progress = Callable[[str, int], Awaitable[None]]


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _course_task(session: AsyncSession, user_id: str, plan_id: str, task_key: str) -> tuple[TrainingPlan, dict]:
    plan = await session.get(TrainingPlan, plan_id)
    if plan is None or plan.user_id != user_id:
        raise not_found("训练计划")
    task = next((item for item in plan.tasks or [] if item.get("key") == task_key and item.get("actionType") == "COURSE"), None)
    if task is None:
        raise not_found("微课任务")
    return plan, task


def _available(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _describe(key: str, engine: str) -> dict:
    chapters = []
    sidecar = settings.lesson_video_dir_path / f"{key}.json"
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("chapters"), list):
            chapters = payload["chapters"]
    except (OSError, ValueError):
        pass
    return {"url": f"/media/lessons/{key}.mp4", "key": key, "engine": engine, "chapters": chapters}


def _cached_video(task: dict, lesson: dict, engine: str) -> dict | None:
    prefix = renderer.lesson_key(lesson)
    known = {
        f"{prefix}-remotion": "remotion",
        f"{prefix}-remotion-python": "python-fallback",
        f"{prefix}-python": "python",
        prefix: "legacy",
    }
    resolved = engine
    if resolved == "auto":
        resolved = settings.lesson_video_engine if settings.lesson_video_engine in {"python", "remotion"} else "python"
    candidates = [f"{prefix}-{resolved}"]
    if resolved == "remotion":
        candidates.append(f"{prefix}-remotion-python")
    if engine == "auto":
        saved = task.get("lessonVideo")
        if isinstance(saved, dict) and saved.get("lessonKey") == prefix and saved.get("key") in known:
            candidates.insert(0, saved["key"])
        candidates.extend(known)
    for key in dict.fromkeys(candidates):
        if key in known and _available(settings.lesson_video_dir_path / f"{key}.mp4"):
            return _describe(key, known[key])
    return None


async def _find_job(session: AsyncSession, plan_id: str, task_key: str) -> LessonVideoJob | None:
    return await session.scalar(
        select(LessonVideoJob)
        .where(LessonVideoJob.plan_id == plan_id, LessonVideoJob.task_key == task_key)
        .order_by(LessonVideoJob.updated_at.desc())
        .limit(1)
    )


def _job_url(job: LessonVideoJob) -> str | None:
    return f"/media/lessons/{job.video_key}.mp4" if job.video_key else None


def _job_state(job: LessonVideoJob) -> dict:
    return {
        "jobId": job.id,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "url": _job_url(job) if job.status == "DONE" else None,
        "chapters": job.chapters or [],
        "error": job.error,
    }


async def enqueue_lesson_video_job(
    session: AsyncSession, plan_id: str, task_key: str = "course", engine: str = "auto", force: bool = False
) -> LessonVideoJob:
    """建一条待渲染任务；已有 DONE 或同键 PENDING/RUNNING 时不重复排队（幂等）。"""
    job = await _find_job(session, plan_id, task_key)
    if job is not None and not force and job.status in {"DONE", "PENDING", "RUNNING"}:
        return job
    if job is None:
        job = LessonVideoJob(plan_id=plan_id, task_key=task_key, status="PENDING", progress=0)
        session.add(job)
    job.status = "PENDING"
    job.progress = 0
    job.stage = FORCE_STAGE if force else QUEUED_STAGE
    job.engine = engine
    if force:
        job.video_key = None
        job.chapters = None
    job.error = None
    job.updated_at = _now()
    await session.commit()
    return job


async def start_lesson_video(
    session: AsyncSession, user_id: str, plan_id: str, task_key: str = "course", engine: str = "auto", force: bool = False
) -> dict:
    """秒回：已有成片直接给结果，否则入队并返回当前任务进度。"""
    _plan, task = await _course_task(session, user_id, plan_id, task_key)
    lesson = task.get("lesson")
    if not force and isinstance(lesson, dict) and lesson.get("steps"):
        found = _cached_video(task, lesson, engine)
        if found is not None:
            return {
                "jobId": None,
                "status": "DONE",
                "progress": 100,
                "stage": DONE_STAGE,
                "url": found["url"],
                "chapters": found["chapters"],
                "key": found["key"],
                "engine": found["engine"],
                "error": None,
            }
    job = await enqueue_lesson_video_job(session, plan_id, task_key, engine, force)
    return _job_state(job)


async def get_job_state(session: AsyncSession, user_id: str, plan_id: str, task_key: str = "course", engine: str = "auto") -> dict:
    """轮询接口：任务进度优先；没有任务时回落为无副作用的缓存探测。"""
    _plan, task = await _course_task(session, user_id, plan_id, task_key)
    job = await _find_job(session, plan_id, task_key)
    if job is None:
        lesson = task.get("lesson")
        found = _cached_video(task, lesson, engine) if isinstance(lesson, dict) and lesson.get("steps") else None
        return {
            "jobId": None,
            "status": "DONE" if found else "NONE",
            "progress": 100 if found else 0,
            "stage": DONE_STAGE if found else "",
            "url": found["url"] if found else None,
            "chapters": found["chapters"] if found else [],
            "error": None,
        }
    return _job_state(job)


async def reset_stale_jobs(session: AsyncSession, *, timeout_seconds: int = JOB_STALE_SECONDS) -> int:
    """把卡死的 RUNNING 放回队列，避免进程被杀后任务永远占位。"""
    cutoff = _now() - timedelta(seconds=timeout_seconds)
    rows = (
        await session.scalars(
            select(LessonVideoJob).where(
                LessonVideoJob.status == "RUNNING", LessonVideoJob.updated_at < cutoff
            )
        )
    ).all()
    for job in rows:
        job.status = "PENDING"
        job.progress = 0
        job.stage = QUEUED_STAGE
        job.error = None
        job.updated_at = _now()
    if rows:
        await session.commit()
        logger.warning("lesson_video.jobs_requeued count=%s", len(rows))
    return len(rows)


async def fail_overdue_jobs(session: AsyncSession, *, seconds: float | None = None) -> int:
    """运行期看门狗：超过阈值还停在 RUNNING 的任务直接判失败，别让它堵死单并发队列。"""
    limit = float(settings.lesson_video_timeout_seconds if seconds is None else seconds) + STALE_GRACE_SECONDS
    cutoff = _now() - timedelta(seconds=limit)
    rows = (
        await session.scalars(
            select(LessonVideoJob).where(
                LessonVideoJob.status == "RUNNING", LessonVideoJob.updated_at < cutoff
            )
        )
    ).all()
    for job in rows:
        job.status = "FAILED"
        job.stage = FAILED_STAGE
        job.error = f"任务超过 {int(limit)} 秒无进展，已判定失败，请重试"
        job.updated_at = _now()
    if rows:
        await session.commit()
        logger.warning("lesson_video.jobs_overdue count=%s", len(rows))
    return len(rows)


async def _claim_next_job(session: AsyncSession) -> tuple[LessonVideoJob, bool] | None:
    job = await session.scalar(
        select(LessonVideoJob)
        .where(LessonVideoJob.status == "PENDING")
        .order_by(LessonVideoJob.updated_at.asc())
        .limit(1)
    )
    if job is None:
        return None
    force = job.stage == FORCE_STAGE
    job.status = "RUNNING"
    job.progress = 0
    job.stage = QUEUED_STAGE
    job.updated_at = _now()
    await session.commit()
    return job, force


def _progress_reporter(session: AsyncSession, job: LessonVideoJob) -> Progress:
    async def report(stage: str, progress: int) -> None:
        job.stage = stage
        job.progress = progress
        job.updated_at = _now()
        await session.commit()

    return report


async def process_next_job(session: AsyncSession | None = None) -> dict | None:
    """worker 单次 tick：认领最老的一条 PENDING 并执行；没有任务时返回 None。"""
    if session is None:
        from app.db.base import session_factory

        async with session_factory() as opened:
            return await process_next_job(opened)
    claimed = await _claim_next_job(session)
    if claimed is None:
        return None
    job, force = claimed
    plan = await session.get(TrainingPlan, job.plan_id)
    if plan is None:
        job.status = "FAILED"
        job.stage = FAILED_STAGE
        job.error = "训练计划已删除"
        job.updated_at = _now()
        await session.commit()
        return _job_state(job)
    try:
        result = await create_lesson_video(
            session,
            plan.user_id,
            job.plan_id,
            job.task_key,
            job.engine or "auto",
            force=force,
            progress=_progress_reporter(session, job),
        )
    except Exception as exc:  # noqa: BLE001 - 任务失败只落库，不打断 worker 循环
        job.status = "FAILED"
        job.stage = FAILED_STAGE
        # AppError 是 dataclass，str() 出来是元组样式，取 detail 才是给用户看的一句话
        job.error = (exc.detail if isinstance(exc, AppError) else str(exc) or type(exc).__name__)[:480]
        job.updated_at = _now()
        await session.commit()
        logger.warning("lesson_video.job_failed job=%s error_type=%s", job.id, type(exc).__name__)
        return _job_state(job)
    job.status = "DONE"
    job.progress = 100
    job.stage = DONE_STAGE
    job.engine = result.get("engine") or job.engine
    job.video_key = result.get("key")
    job.chapters = result.get("chapters") or []
    job.error = None
    job.updated_at = _now()
    await session.commit()
    logger.info("lesson_video.job_done job=%s engine=%s", job.id, job.engine)
    return _job_state(job)


async def get_lesson_video(session: AsyncSession, user_id: str, plan_id: str, task_key: str, engine: str = "auto") -> dict:
    """查询只读已有课程，不调用模型、渲染或改写学习记录。"""
    _plan, task = await _course_task(session, user_id, plan_id, task_key)
    lesson = task.get("lesson")
    if isinstance(lesson, dict) and lesson.get("steps"):
        found = _cached_video(task, lesson, engine)
        if found:
            return found
    return {"url": None, "chapters": []}


async def create_lesson_video(
    session: AsyncSession,
    user_id: str,
    plan_id: str,
    task_key: str,
    engine: str = "auto",
    force: bool = False,
    *,
    progress: Progress | None = None,
) -> dict:
    async def report(stage: str, value: int) -> None:
        if progress is not None:
            await progress(stage, value)

    await report(DRAFT_STAGE, 15)
    result = await personalized_lesson(session, user_id, plan_id, task_key, force=force)
    lesson = result.get("lesson") or {}
    if not lesson.get("steps"):
        raise AppError(422, "LESSON_EMPTY", "这门微课还没有可渲染的内容")
    plan, task = await _course_task(session, user_id, plan_id, task_key)
    found = _cached_video(task, lesson, engine)
    if found is None:
        resolved = engine
        if resolved == "auto":
            resolved = settings.lesson_video_engine if settings.lesson_video_engine in {"python", "remotion"} else "python"
        key = f"{renderer.lesson_key(lesson)}-{resolved}"
        target = settings.lesson_video_dir_path / f"{key}.mp4"
        await report(NARRATION_STAGE, 45)
        rendering = asyncio.create_task(
            asyncio.to_thread(
                renderer.render_video_with_fallback, resolved, lesson, target, key, plan.focus_dimension
            )
        )
        # 渲染在子线程里跑，先落 75 让前端看到「渲染中」，再等结果
        await report(RENDER_STAGE, 75)
        timeout = float(settings.lesson_video_timeout_seconds)
        try:
            actual_engine, target, key = await asyncio.wait_for(rendering, timeout=timeout)
        except asyncio.TimeoutError as exc:
            # to_thread 里的线程无法真正取消（渲染子进程可能还在），这里只保证 worker 立刻脱身，
            # 残留任务由运行期看门狗与启动重置兜底。
            raise AppError(504, "LESSON_VIDEO_TIMEOUT", f"渲染超时（超过 {int(timeout)} 秒），请重试") from exc
        if not _available(target):
            raise AppError(503, "LESSON_VIDEO_EMPTY", "课程视频未生成成功，请稍后重试")
        found = _describe(key, actual_engine)

    # 渲染期间可能更新了学习进度；重新读取后只追加视频信息。
    await session.refresh(plan, attribute_names=["tasks"])
    tasks = copy.deepcopy(plan.tasks or [])
    current = next((item for item in tasks if item.get("key") == task_key and item.get("actionType") == "COURSE"), None)
    prefix = renderer.lesson_key(lesson)
    if current is None or renderer.lesson_key(current.get("lesson") or {}) != prefix:
        raise AppError(409, "LESSON_CHANGED", "课程内容已更新，请重新打开课程")
    record = {"lessonKey": prefix, "key": found["key"], "engine": found["engine"]}
    if current.get("lessonVideo") != record:
        current["lessonVideo"] = record
        plan.tasks = tasks
        flag_modified(plan, "tasks")
        await session.commit()
    return found
