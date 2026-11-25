"""Independent transfer questions inside a completed plan; no model generation."""
import copy
import hashlib
import re

from sqlalchemy import select
from app.core.errors import AppError, not_found
from app.db.models import Evaluation, Message, ResumeContext, Scene, TrainingPlan, TrainingSession
from app.features.training.rubrics import new_context
from app.features.scenes.taxonomy import normalize_bank

QUESTIONS = {
    "transaction": [
        "优惠券只能核销一次。两个终端同时核销同一张券时，如何约束数据、处理重试并验证结果？",
        "预约系统只剩一个名额，同一用户还可能重复提交。请说明并发处理、幂等边界和验证方法。",
        "账户余额同时发生两笔扣款，业务要求余额不得为负。你如何实现并验证失败重试后的结果？",
    ],
    "cache": [
        "商品价格允许短暂延迟，但结算必须使用正确价格。你会如何设计缓存读取、更新与失败处理，并验证边界？",
        "活动信息有缓存，后台可能同时修改和下架活动。你如何明确一致性要求，并验证失效失败时的处理？",
        "用户权限发生变更后缓存仍未过期。如何根据风险选择一致性方案，并验证失效与并发边界？",
    ],
    "diagnosis": [
        "文件上传接口的 P95 延迟突然升高，但错误率未变。你会先核实什么，再如何定位、止损和验证？",
        "只有一个地区的查询变慢，数据库总体监控正常。你如何定位影响范围、收集证据并验证修复？",
        "发布后请求量没有明显变化，但超时增加。请说明排查证据、止损决策及修复验证步骤。",
    ],
}


async def source_context(db, user_id, tasks):
    source_id = next((item.get("sourceSessionId") for item in tasks if item.get("sourceSessionId")), None)
    baseline = await db.get(TrainingSession, source_id) if source_id else None
    if not baseline or baseline.user_id != user_id:
        return None, None, None
    scene = await db.get(Scene, baseline.scene_id)
    if not scene:
        return None, None, None
    context = copy.deepcopy(baseline.assessment_context) or new_context(scene, normalize_bank(baseline.question_plan or scene.question_bank))
    return baseline, scene, context


def candidate_questions(context, difficulty=None):
    candidates = []
    for criterion in context.get('criteria', []):
        if 'transferQuestionSpecs' in criterion:
            questions = [item['text'] for item in criterion['transferQuestionSpecs']
                         if difficulty is None or item['difficulty'] == difficulty]
        else:
            # Old snapshots and administrator-authored banks keep their original questions.
            questions = criterion.get('transferQuestions', QUESTIONS.get(criterion['id'], []))
        candidates.extend((criterion, question) for question in questions)
    return candidates


async def transfer_overview(db, plan, tasks) -> dict:
    finished = plan.status == "COMPLETED" and bool(tasks) and all(item["completed"] for item in tasks)
    baseline, scene, context = await source_context(db, plan.user_id, tasks) if finished else (None, None, None)
    available = bool(baseline and scene.active and len(candidate_questions(context, scene.difficulty)) >= 2)
    rows = (await db.execute(select(TrainingSession, Evaluation).outerjoin(Evaluation, Evaluation.session_id == TrainingSession.id)
        .where(TrainingSession.user_id == plan.user_id, TrainingSession.plan_id == plan.id,
               TrainingSession.task_key == "transfer").order_by(TrainingSession.started_at.desc()).limit(10))).all()
    return {"available": available, "reason": "完成原计划后，可用新情境独立检查方法是否能迁移。" if not finished else
            "本次更换题面与约束，不提供提示或参考回答，也不计入同题趋势。" if available else "当前岗位尚未配置迁移题，或原训练已删除。",
            "attempts": [{"sessionId": training.id, "status": training.status,
                          "createdAt": training.started_at.isoformat(),
                          "result": ((evaluation.assessment or {}).get("transfer") or {}).get("result") if evaluation else None}
                         for training, evaluation in rows]}


async def start_transfer(db, user_id: str, plan_id: str) -> str:
    plan = await db.scalar(select(TrainingPlan).where(TrainingPlan.id == plan_id).with_for_update())
    if plan is None or plan.user_id != user_id:
        raise not_found("训练计划")
    tasks = plan.tasks or []
    if plan.status != "COMPLETED" or not tasks or not all(item.get("completed") for item in tasks):
        raise AppError(409, "TRANSFER_PLAN_INCOMPLETE", "请先完成原计划，再进行新题迁移")
    existing = await db.scalar(select(TrainingSession).where(TrainingSession.user_id == user_id,
        TrainingSession.plan_id == plan_id, TrainingSession.task_key == "transfer", TrainingSession.status == "ACTIVE"))
    if existing:
        return existing.id
    baseline, scene, context = await source_context(db, user_id, tasks)
    if not baseline or not scene.active:
        raise AppError(409, "TRANSFER_SOURCE_UNAVAILABLE", "原训练或场景不可用，无法开始迁移")
    candidates = candidate_questions(context, scene.difficulty)
    history = (await db.scalars(select(Message.content).join(TrainingSession, TrainingSession.id == Message.session_id)
        .where(TrainingSession.user_id == user_id, Message.speaker == "AI"))).all()
    normalize = lambda text: re.sub(r"[\s，。！？、,.!?]", "", text)
    seen = [normalize(question) for question in history]
    def was_seen(criterion, question):
        base = next((item.get('baseText', question) for item in criterion.get('transferQuestionSpecs', [])
                     if item['text'] == question), question)
        return any(normalize(base) in old for old in seen)
    selected = []
    chosen_criteria = set()
    for criterion, question in candidates:
        if was_seen(criterion, question):
            continue
        if criterion["id"] in chosen_criteria:
            continue
        selected.append((criterion, question))
        chosen_criteria.add(criterion["id"])
        if len(selected) == 2:
            break
    if len(selected) < 2:
        for criterion, question in candidates:
            if any(question == value for _, value in selected) or was_seen(criterion, question):
                continue
            selected.append((criterion, question))
            if len(selected) == 2:
                break
    if len(selected) < 2:
        raise AppError(409, "TRANSFER_QUESTIONS_EXHAUSTED", "现有新题不足，请管理员在场景考察标准中补充迁移题")
    questions = [{"text": question, "dimension": plan.focus_dimension, "difficulty": scene.difficulty} for _, question in selected]
    context.update(purpose="TRANSFER", adaptiveEnabled=False, evidenceTrace=[], coverage={}, hintUses=0)
    context["transfer"] = {"planId": plan.id, "baselineSessionId": baseline.id,
        "competencies": [criterion["id"] for criterion, _ in selected], "difficulty": scene.difficulty,
        "questionSetId": hashlib.sha256(str(questions).encode()).hexdigest()[:16],
        "notice": "按平台已有作答记录筛选的新题面；与原题分开查看，不推断招聘通过率。"}
    context['transfer']['questionSpecs'] = [copy.deepcopy(spec) for criterion, question in selected
        for spec in criterion.get('transferQuestionSpecs', []) if spec['text'] == question]
    context['transfer']['equivalenceValidated'] = False
    context['transfer']['difficultyBasis'] = 'AUTHOR_TAGGED_NOT_EMPIRICALLY_EQUATED'
    training = TrainingSession(user_id=user_id, scene_id=scene.id, channel="TEXT", status="ACTIVE",
        max_rounds=2, covered_count=1, question_plan=questions, jd_text=baseline.jd_text,
        depth="STANDARD", mode="STANDARD", plan_id=plan.id, task_key="transfer", assessment_context=context)
    db.add(training)
    await db.flush()
    db.add(Message(session_id=training.id, round_no=0, speaker="AI", content=questions[0]["text"]))
    resume = await db.get(ResumeContext, baseline.id)
    if resume:
        db.add(ResumeContext(session_id=training.id, filename=resume.filename, content=resume.content))
    await db.commit()
    return training.id
