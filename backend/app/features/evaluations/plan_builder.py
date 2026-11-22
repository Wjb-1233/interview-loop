"""Build and persist a plan from one report; preserve cumulative plan policy."""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Course, Message, Scene, TrainingPlan, TrainingSession
from app.features.evaluations.schemas import EvaluationPayload
from app.features.plans.generation import fallback_plan, generate_plan


async def create_training_plan(
    session: AsyncSession,
    user_id: str,
    evaluation: EvaluationPayload,
    training: TrainingSession,
    user_messages: list[Message],
    *,
    allow_generation: bool = True,
    focus_override: str | None = None,
) -> str:
    labels = {
        "logic": "内容与逻辑",
        "relevance": "贴合问题",
        "correctness": "信息完整",
        "concision": "表达干净",
    }
    score_values = evaluation.scores.model_dump()
    score_values.pop("appropriateness", None)  # 得体性已不再单独评分
    weakest_key = min(score_values, key=score_values.get)
    if focus_override:
        focus = focus_override
        weakest_key = next((key for key, label in labels.items() if label == focus), weakest_key)
    else:
        # 有历史能力值时以能力值最低的维度为准，与场景推荐保持一致
        from app.features.plans.personalization import skill_snapshot

        snapshot = await skill_snapshot(session, user_id)
        if snapshot:
            weakest_key = min(snapshot, key=snapshot.get)
        focus = labels[weakest_key]
    original_scene = await session.get(Scene, training.scene_id)
    course = await session.scalar(
        select(Course)
        .where(Course.dimension == focus, Course.active.is_(True))
        .order_by(Course.created_at)
        .limit(1)
    )
    course_title = course.title if course else f"{focus}沟通技巧"
    course_content = course.content if course else "结论先行；使用事实；明确下一步"
    if allow_generation:
        draft = await generate_plan(
            focus=focus,
            scores=score_values,
            suggestions=evaluation.suggestions,
            user_lines=[message.content for message in user_messages],
            scene_title=original_scene.title if original_scene else "原场景",
            course_title=course_title,
            course_content=course_content,
        )
    else:
        draft = fallback_plan(focus, course_title, course_content)
    lesson = draft.lesson.model_dump(by_alias=True)
    plan_title = draft.title.replace("四步", "").replace("三步", "").strip() or f"{focus}提升计划"
    scene_tasks = [
        {"key": "session-review", "day": 1, "task": "查看原话证据和逐轮复盘，确认本场薄弱点", "actionType": "REPORT", "sourceSessionId": training.id, "completed": False},
        {"key": "rewrite", "day": 1, "task": "选一题，提交保留真实事实的改写并通过教练检查", "actionType": "REWRITE", "sourceSessionId": training.id, "completed": False},
    ]

    latest_sequence = await session.scalar(
        select(func.max(TrainingPlan.sequence)).where(TrainingPlan.user_id == user_id)
    )
    plan = TrainingPlan(
        user_id=user_id,
        focus_dimension=focus,
        title=plan_title,
        sequence=(latest_sequence or 0) + 1,
        tasks=scene_tasks + [
            {
                "key": "course",
                "day": 1,
                "task": f"学习微课与可选视频《{lesson['title']}》，学完再练",
                "actionType": "COURSE",
                "courseId": course.id if course else None,
                "sourceSessionId": training.id,
                "lesson": lesson,
                "completedSteps": [],
                "practiceAnswer": None,
                "practiceFeedback": None,
                "practicePassed": False,
                "practiceDegraded": False,
                "completed": False,
                "completedAt": None,
                "evidence": None,
            },
            {"key": "retest", "day": 2, "task": "按相同场景、方式和追问强度复测，对比四维变化", "actionType": "RETEST", "sceneId": training.scene_id, "sourceSessionId": training.id, "channel": training.channel or "TEXT", "depth": training.depth or "STANDARD", "completed": False},
        ],
    )
    session.add(plan)
    await session.flush()

    # 未完成的计划保留，但最多同时进行 3 份；更早的自动归档，历史仍可查看
    active_plans = list(
        (
            await session.scalars(
                select(TrainingPlan)
                .where(TrainingPlan.user_id == user_id, TrainingPlan.status == "ACTIVE")
                .order_by(TrainingPlan.sequence.desc())
            )
        ).all()
    )
    for stale in active_plans[3:]:
        stale.status = "ARCHIVED"
    await session.commit()
    return plan.id

