"""微课视频后台队列：入队幂等、worker 推进、卡死重置与进度查询。"""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.config import settings
from app.db.base import session_factory
from app.db.models import LessonVideoJob, TrainingPlan
from app.features.plans import lesson_videos
from app.features.plans.generation import fallback_plan
from app.main import app

STATE_URL = "/api/v1/training-plans/{plan_id}/lesson/video/state"
VIDEO_URL = "/api/v1/training-plans/{plan_id}/lesson/video"


@pytest.fixture
def queue(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "lesson_video_dir", str(tmp_path))
    monkeypatch.setattr(settings, "lesson_video_engine", "python")
    with TestClient(app, client=(f"lesson-job-{uuid4().hex}", 50000)) as client:
        registered = client.post("/api/v1/auth/register", json={
            "email": f"lesson-job-{uuid4().hex}@example.com",
            "password": "LessonJob123!",
            "displayName": "视频队列",
            "consent": True,
        }).json()["data"]
        lesson = fallback_plan("内容与逻辑", "结论先行练习", "先给结论；补充事实；明确行动").lesson.model_dump(by_alias=True)
        task = {
            "key": "course",
            "actionType": "COURSE",
            "day": 1,
            "task": "学习微课",
            "lesson": lesson,
            "completed": False,
            "completedSteps": [],
        }

        async def create_plan():
            async with session_factory() as session:
                plan = TrainingPlan(
                    user_id=registered["user"]["id"],
                    focus_dimension="内容与逻辑",
                    title="视频队列计划",
                    sequence=1,
                    status="ACTIVE",
                    tasks=[task],
                )
                session.add(plan)
                await session.commit()
                return plan.id

        plan_id = asyncio.run(create_plan())
        client.headers.update({"Authorization": f"Bearer {registered['accessToken']}"})
        yield client, plan_id


def latest_job(plan_id: str) -> LessonVideoJob | None:
    async def read():
        async with session_factory() as session:
            return await session.scalar(
                select(LessonVideoJob)
                .where(LessonVideoJob.plan_id == plan_id)
                .order_by(LessonVideoJob.updated_at.desc())
                .limit(1)
            )

    return asyncio.run(read())


def job_count(plan_id: str) -> int:
    async def read():
        async with session_factory() as session:
            rows = await session.scalars(select(LessonVideoJob).where(LessonVideoJob.plan_id == plan_id))
            return len(list(rows))

    return asyncio.run(read())


def patch_job(plan_id: str, **changes) -> None:
    async def apply():
        async with session_factory() as session:
            job = await session.scalar(
                select(LessonVideoJob).where(LessonVideoJob.plan_id == plan_id).limit(1)
            )
            if job is None:
                job = LessonVideoJob(plan_id=plan_id, task_key="course", status="PENDING", progress=0)
                session.add(job)
            for field, value in changes.items():
                setattr(job, field, value)
            await session.commit()

    asyncio.run(apply())


def drop_other_jobs(plan_id: str) -> None:
    """全部测试共用一个库：先清掉别的计划留下的待办，保证 tick 认领的就是本用例的。"""

    async def clean():
        async with session_factory() as session:
            await session.execute(delete(LessonVideoJob).where(LessonVideoJob.plan_id != plan_id))
            await session.commit()

    asyncio.run(clean())


def test_enqueue_is_idempotent(queue):
    client, plan_id = queue
    first = client.post(VIDEO_URL.format(plan_id=plan_id), json={}).json()["data"]
    assert first["status"] == "PENDING"
    assert first["progress"] == 0
    assert first["jobId"]
    assert first["stage"] in {"排队", "重新生成"}

    again = client.post(VIDEO_URL.format(plan_id=plan_id), json={}).json()["data"]
    assert again["jobId"] == first["jobId"]
    assert again["status"] == "PENDING"
    assert job_count(plan_id) == 1


def test_worker_tick_renders_pending_job_to_done(queue, monkeypatch):
    client, plan_id = queue
    drop_other_jobs(plan_id)
    client.post(VIDEO_URL.format(plan_id=plan_id), json={})

    stages: list[tuple[str, int]] = []

    async def fake_create(session, user_id, plan_id_arg, task_key, engine="auto", force=False, *, progress=None):
        assert force is False
        await progress("备稿", 15)
        stages.append(("备稿", 15))
        return {
            "url": "/media/lessons/fake-course.mp4",
            "key": "fake-course",
            "engine": "python",
            "chapters": [{"title": "先给结论", "start": 0, "duration": 12}],
        }

    monkeypatch.setattr(lesson_videos, "create_lesson_video", fake_create)
    result = asyncio.run(lesson_videos.process_next_job())
    assert result["status"] == "DONE"

    job = latest_job(plan_id)
    assert (job.status, job.progress, job.stage) == ("DONE", 100, "完成")
    assert job.video_key == "fake-course"
    assert job.chapters == [{"title": "先给结论", "start": 0, "duration": 12}]
    assert job.engine == "python"
    assert stages == [("备稿", 15)]

    state = client.get(STATE_URL.format(plan_id=plan_id)).json()["data"]
    assert state["status"] == "DONE"
    assert state["progress"] == 100
    assert state["url"] == "/media/lessons/fake-course.mp4"
    assert state["chapters"] == [{"title": "先给结论", "start": 0, "duration": 12}]

    assert asyncio.run(lesson_videos.process_next_job()) is None


def test_worker_failure_marks_job_failed_without_raising(queue, monkeypatch):
    client, plan_id = queue
    drop_other_jobs(plan_id)
    client.post(VIDEO_URL.format(plan_id=plan_id), json={})

    async def boom(*_args, **_kwargs):
        raise RuntimeError("渲染进程崩了")

    monkeypatch.setattr(lesson_videos, "create_lesson_video", boom)
    result = asyncio.run(lesson_videos.process_next_job())
    assert result["status"] == "FAILED"
    job = latest_job(plan_id)
    assert job.status == "FAILED"
    assert job.stage == "失败"
    assert "渲染进程崩了" in job.error


def test_stale_running_job_is_requeued(queue):
    client, plan_id = queue
    client.post(VIDEO_URL.format(plan_id=plan_id), json={})
    patch_job(
        plan_id,
        status="RUNNING",
        progress=45,
        stage="旁白合成",
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=11),
    )

    async def reset():
        async with session_factory() as session:
            return await lesson_videos.reset_stale_jobs(session)

    assert asyncio.run(reset()) == 1
    job = latest_job(plan_id)
    assert (job.status, job.progress, job.stage) == ("PENDING", 0, "排队")


def test_force_requeues_done_job_and_plain_click_skips_it(queue):
    client, plan_id = queue
    first = client.post(VIDEO_URL.format(plan_id=plan_id), json={}).json()["data"]
    patch_job(plan_id, status="DONE", progress=100, stage="完成", video_key="old-course")

    skipped = client.post(VIDEO_URL.format(plan_id=plan_id), json={}).json()["data"]
    assert skipped["status"] == "DONE"
    assert skipped["url"] == "/media/lessons/old-course.mp4"
    assert job_count(plan_id) == 1

    forced = client.post(VIDEO_URL.format(plan_id=plan_id), json={"force": True}).json()["data"]
    assert forced["jobId"] == first["jobId"]
    assert (forced["status"], forced["progress"]) == ("PENDING", 0)
    assert forced["url"] is None
    job = latest_job(plan_id)
    assert (job.status, job.progress, job.stage, job.video_key) == ("PENDING", 0, "重新生成", None)
    assert job_count(plan_id) == 1


def test_render_timeout_fails_job_and_worker_moves_on(queue, monkeypatch):
    client, plan_id = queue
    drop_other_jobs(plan_id)
    client.post(VIDEO_URL.format(plan_id=plan_id), json={})
    monkeypatch.setattr(settings, "lesson_video_timeout_seconds", 0.2)

    def stuck_render(*_args, **_kwargs):
        time.sleep(3)  # 模拟 remotion/ffmpeg 卡住不返回
        return "python", None, "stuck"

    monkeypatch.setattr("app.features.lessons.video.render_video_with_fallback", stuck_render)

    async def timed_tick():
        # 在事件循环内部计时：出循环时 asyncio.run 会等线程池收尾，那不是 worker 的耗时
        started = time.perf_counter()
        outcome = await lesson_videos.process_next_job()
        return outcome, time.perf_counter() - started

    result, elapsed = asyncio.run(timed_tick())
    assert result["status"] == "FAILED"
    assert "渲染超时" in result["error"]
    assert elapsed < 2  # worker 没有被卡住的线程拖住
    job = latest_job(plan_id)
    assert (job.status, job.stage) == ("FAILED", "失败")

    async def fake_create(session, user_id, plan_id_arg, task_key, engine="auto", force=False, *, progress=None):
        return {"url": "/media/lessons/next-key.mp4", "key": "next-key", "engine": "python", "chapters": []}

    monkeypatch.setattr(lesson_videos, "create_lesson_video", fake_create)
    client.post(VIDEO_URL.format(plan_id=plan_id), json={"force": True})
    assert asyncio.run(lesson_videos.process_next_job())["status"] == "DONE"


def test_runtime_watchdog_fails_stale_running_job(queue, monkeypatch):
    client, plan_id = queue
    monkeypatch.setattr(settings, "lesson_video_timeout_seconds", 480.0)
    client.post(VIDEO_URL.format(plan_id=plan_id), json={})

    async def watchdog():
        async with session_factory() as session:
            return await lesson_videos.fail_overdue_jobs(session)

    patch_job(plan_id, status="RUNNING", progress=75, stage="渲染", updated_at=datetime.now(timezone.utc))
    asyncio.run(watchdog())
    assert latest_job(plan_id).status == "RUNNING"  # 新鲜的 RUNNING 不动

    patch_job(plan_id, updated_at=datetime.now(timezone.utc) - timedelta(minutes=20))
    assert asyncio.run(watchdog()) >= 1
    job = latest_job(plan_id)
    assert (job.status, job.stage) == ("FAILED", "失败")
    assert "无进展" in job.error


def test_state_endpoint_reports_each_status(queue):
    client, plan_id = queue
    url = STATE_URL.format(plan_id=plan_id)

    idle = client.get(url).json()["data"]
    assert idle["status"] == "NONE"
    assert idle["progress"] == 0
    assert idle["url"] is None

    patch_job(plan_id, status="PENDING", progress=0, stage="排队", error=None)
    pending = client.get(url).json()["data"]
    assert (pending["status"], pending["progress"], pending["stage"]) == ("PENDING", 0, "排队")
    assert pending["url"] is None and pending["error"] is None

    patch_job(plan_id, status="RUNNING", progress=75, stage="渲染")
    running = client.get(url).json()["data"]
    assert (running["status"], running["progress"], running["stage"]) == ("RUNNING", 75, "渲染")

    chapters = [{"title": "先给结论", "start": 0, "duration": 12}]
    patch_job(plan_id, status="DONE", progress=100, stage="完成", video_key="state-key", chapters=chapters)
    done = client.get(url).json()["data"]
    assert done["status"] == "DONE"
    assert done["progress"] == 100
    assert done["url"] == "/media/lessons/state-key.mp4"
    assert done["chapters"] == chapters
    assert done["error"] is None

    patch_job(plan_id, status="FAILED", progress=45, stage="失败", error="渲染超时")
    failed = client.get(url).json()["data"]
    assert failed["status"] == "FAILED"
    assert failed["error"] == "渲染超时"
    assert failed["url"] is None
