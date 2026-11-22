"""课程视频生成后应能跨页面、跨引擎配置回看。"""

import asyncio
import copy
import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.db.base import session_factory
from app.db.models import LessonVideoJob, TrainingPlan
from app.features.lessons.video import lesson_key
from app.features.plans.generation import fallback_plan
from app.features.plans.lesson_videos import process_next_job
from app.main import app


@pytest.fixture
def replay(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "lesson_video_dir", str(tmp_path))
    monkeypatch.setattr(settings, "lesson_video_engine", "remotion")
    with TestClient(app, client=(f"replay-{uuid4().hex}", 50000)) as client:
        registered = client.post("/api/v1/auth/register", json={
            "email": f"replay-{uuid4().hex}@example.com", "password": "ReplayTest123!",
            "displayName": "课程回看", "consent": True,
        }).json()["data"]
        lesson = fallback_plan("内容与逻辑", "结论先行练习", "先给结论；补充事实；明确行动").lesson.model_dump(by_alias=True)
        lesson["aiGenerated"] = True
        task = {"key": "course", "actionType": "COURSE", "day": 1, "task": "学习微课", "lesson": lesson, "completed": False, "completedSteps": []}

        async def create():
            async with session_factory() as session:
                plan = TrainingPlan(user_id=registered["user"]["id"], focus_dimension="内容与逻辑", title="微课回看计划", sequence=1, status="ACTIVE", tasks=[task])
                session.add(plan)
                await session.commit()
                return plan.id

        plan_id = asyncio.run(create())
        yield client, {"Authorization": f"Bearer {registered['accessToken']}"}, plan_id, lesson, tmp_path


def saved_task(plan_id):
    async def read():
        async with session_factory() as session:
            plan = await session.get(TrainingPlan, plan_id)
            return copy.deepcopy(plan.tasks[0])
    return asyncio.run(read())


def oldest_job(plan_id):
    """测试共用同一个库：把本计划的待办改成最老的，保证 tick 认领的就是它。"""

    async def mark():
        async with session_factory() as session:
            job = await session.scalar(select(LessonVideoJob).where(LessonVideoJob.plan_id == plan_id).limit(1))
            job.updated_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
            await session.commit()

    asyncio.run(mark())


def update_task(plan_id, changes):
    async def update():
        async with session_factory() as session:
            plan = await session.get(TrainingPlan, plan_id)
            task = copy.deepcopy(plan.tasks[0])
            task.update(changes)
            plan.tasks = [task]
            await session.commit()
    asyncio.run(update())


@pytest.mark.parametrize("suffix", ["remotion", "remotion-python", "python", ""])
def test_existing_video_is_found_without_rendering(replay, monkeypatch, suffix):
    client, headers, plan_id, lesson, directory = replay
    key = lesson_key(lesson) + (f"-{suffix}" if suffix else "")
    (directory / f"{key}.mp4").write_bytes(b"existing-video")
    chapters = [{"title": "先给结论", "start": 0, "duration": 15}]
    (directory / f"{key}.json").write_text(json.dumps({"chapters": chapters}), encoding="utf-8")

    def forbidden(*_args):
        pytest.fail("已经存在的视频不应重新渲染")
    monkeypatch.setattr("app.features.lessons.video.render_video_with_fallback", forbidden)
    before = saved_task(plan_id)
    response = client.get(f"/api/v1/training-plans/{plan_id}/lesson/video", headers=headers)
    assert response.status_code == 200
    assert response.json()["data"]["url"] == f"/media/lessons/{key}.mp4"
    assert response.json()["data"]["chapters"] == chapters
    assert saved_task(plan_id) == before  # 查询不改写课程或学习记录。
    reused = client.post(f"/api/v1/training-plans/{plan_id}/lesson/video", headers=headers, json={})
    assert reused.status_code == 200
    assert reused.json()["data"]["url"] == response.json()["data"]["url"]


def test_reopening_fallback_lesson_does_not_regenerate_content(replay, monkeypatch):
    client, headers, plan_id, lesson, directory = replay
    lesson["aiGenerated"] = False
    update_task(plan_id, {"lesson": lesson})
    key = f"{lesson_key(lesson)}-remotion-python"
    (directory / f"{key}.mp4").write_bytes(b"existing-video")
    calls = []

    async def changed_lesson(**_kwargs):
        calls.append(True)
        return fallback_plan("内容与逻辑", "这次不应生成的新课程", "重新整理；再次确认；重新作答").lesson, {}
    monkeypatch.setattr("app.features.plans.service.generate_lesson_only", changed_lesson)
    response = client.get(f"/api/v1/training-plans/{plan_id}/lesson/video", headers=headers)
    assert calls == []
    assert response.json()["data"]["url"] == f"/media/lessons/{key}.mp4"
    loaded = client.post(f"/api/v1/training-plans/{plan_id}/lesson", headers=headers, json={})
    assert loaded.json()["data"]["lesson"] == lesson
    assert calls == []
    assert saved_task(plan_id)["lesson"] == lesson


def test_saved_video_survives_engine_change_and_learning_progress(replay, monkeypatch):
    client, headers, plan_id, lesson, directory = replay
    renders = []

    def render(_engine, _lesson, target, key, _dimension):
        renders.append(key)
        actual_key = f"{key}-python"
        actual = target.with_name(f"{actual_key}.mp4")
        actual.write_bytes(b"new-video")
        return "python-fallback", actual, actual_key
    monkeypatch.setattr("app.features.lessons.video.render_video_with_fallback", render)
    created = client.post(f"/api/v1/training-plans/{plan_id}/lesson/video", headers=headers, json={})
    assert created.status_code == 200
    assert created.json()["data"]["status"] == "PENDING"
    # 渲染改成后台队列：手动跑一次 worker tick，替身渲染器写出的就是成片
    oldest_job(plan_id)
    assert asyncio.run(process_next_job())["status"] == "DONE"
    video = client.get(f"/api/v1/training-plans/{plan_id}/lesson/video", headers=headers).json()["data"]
    assert saved_task(plan_id)["lessonVideo"]["key"] == video["key"]
    monkeypatch.setattr(settings, "lesson_video_engine", "python")
    step = client.post(f"/api/v1/training-plans/{plan_id}/tasks/course/steps/0/complete", headers=headers)
    assert step.status_code == 200
    reopened = client.get(f"/api/v1/training-plans/{plan_id}/lesson/video", headers=headers).json()["data"]
    assert reopened["url"] == video["url"]
    assert saved_task(plan_id)["lessonVideo"]["key"] == video["key"]
    reused = client.post(f"/api/v1/training-plans/{plan_id}/lesson/video", headers=headers, json={})
    assert reused.json()["data"]["url"] == video["url"]
    assert len(renders) == 1


def test_changing_lesson_does_not_reuse_old_video(replay, monkeypatch):
    client, headers, plan_id, lesson, directory = replay
    old_key = f"{lesson_key(lesson)}-remotion"
    old_file = directory / f"{old_key}.mp4"
    old_file.write_bytes(b"old-video")
    update_task(plan_id, {"lessonVideo": {"lessonKey": lesson_key(lesson), "key": old_key, "engine": "remotion"}})
    replacement = fallback_plan("内容与逻辑", "新的举例练习", "结论清楚；例子具体；总结行动").lesson

    async def change(**_kwargs):
        return replacement, {}
    monkeypatch.setattr("app.features.plans.service.generate_lesson_only", change)
    response = client.post(f"/api/v1/training-plans/{plan_id}/lesson", headers=headers, json={"force": True})
    assert response.status_code == 200
    assert response.json()["data"]["lesson"]["title"] == replacement.title
    assert saved_task(plan_id).get("lessonVideo") is None
    assert client.get(f"/api/v1/training-plans/{plan_id}/lesson/video", headers=headers).json()["data"]["url"] is None
    assert old_file.read_bytes() == b"old-video"


def test_video_query_is_read_only_when_lesson_is_missing(replay, monkeypatch):
    client, headers, plan_id, _lesson, _directory = replay
    update_task(plan_id, {"lesson": None})
    before = saved_task(plan_id)
    response = client.get(f"/api/v1/training-plans/{plan_id}/lesson/video", headers=headers)
    assert response.status_code == 200
    assert response.json()["data"]["url"] is None
    assert saved_task(plan_id) == before


def test_empty_files_and_other_users_video_are_not_returned(replay):
    client, headers, plan_id, lesson, directory = replay
    (directory / f"{lesson_key(lesson)}-remotion.mp4").write_bytes(b"")
    assert client.get(f"/api/v1/training-plans/{plan_id}/lesson/video", headers=headers).json()["data"]["url"] is None
    other = client.post("/api/v1/auth/register", json={"email": f"other-{uuid4().hex}@example.com", "password": "ReplayTest123!", "displayName": "其他学员", "consent": True}).json()["data"]
    response = client.get(f"/api/v1/training-plans/{plan_id}/lesson/video", headers={"Authorization": f"Bearer {other['accessToken']}"})
    assert response.status_code == 404
    assert client.get(f"/api/v1/training-plans/{plan_id}/lesson/video?engine=invalid", headers=headers).status_code == 422
