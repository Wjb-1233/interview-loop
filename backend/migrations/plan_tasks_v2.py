"""Frozen, deterministic conversion for migration 0048; never uses latest training."""
from copy import deepcopy

LABELS = {"逻辑性": "内容与逻辑", "针对性": "贴合问题", "正确性": "信息完整", "感染力": "信息完整", "简洁度": "表达干净", "得体性": "表达干净"}
DEFAULTS = (("course", "COURSE"), ("practice", "TRAINING"), ("rewrite", "REWRITE"), ("retest", "RETEST"))


def upgrade_tasks(raw_tasks, focus, course, sources, active):
    tasks = deepcopy(raw_tasks or [])
    baseline = next((t.get("sourceSessionId") for t in tasks if t.get("sourceSessionId") in sources), None)
    for index, task in enumerate(tasks):
        key, action = DEFAULTS[min(index, len(DEFAULTS)-1)]
        task.setdefault("key", key)
        task.setdefault("actionType", action)
        task.setdefault("day", 1)
        task.setdefault("task", "查看本次训练内容")
        task.setdefault("completed", False)
        task.setdefault("completedAt", None)
        task.setdefault("evidence", None)
        if task.get("dimension") in LABELS:
            task["dimension"] = LABELS[task["dimension"]]
        if task["actionType"] in {"REWRITE", "RETEST", "TRAINING"}:
            source_id = task.get("sourceSessionId") or baseline
            source = sources.get(source_id)
            task["sourceSessionId"] = source_id if source else None
            if source:
                task.setdefault("sceneId", source["scene_id"])
                task.setdefault("channel", source["channel"] or "TEXT")
                task.setdefault("depth", source["depth"] or "STANDARD")
            elif not source_id:
                task["sourceUnavailable"] = True
        if task["actionType"] == "REWRITE":
            task.setdefault("rewriteFeedback", None)
            task.setdefault("rewritePassed", bool(task["completed"]))
            task.setdefault("rewriteDegraded", False)
        if task["actionType"] == "COURSE":
            task.setdefault("courseId", course["id"] if course else None)
            if not task.get("lesson"):
                principles = [p.strip() for p in (course["content"] if course else "结论先行；使用事实；明确下一步").replace("；", ";").split(";") if p.strip()]
                principles += ["给出具体事实并明确下一步"] * 3
                task["lesson"] = {"title": course["title"] if course else f"{focus}沟通技巧", "intro": f"围绕{focus}完成三个小步骤，再用自己的语言作答。当前为离线示例内容。", "steps": [{"title": f"第 {n+1} 步：{p}", "explanation": f"在下一次面试表达中练习“{p}”，并检查听众是否能抓住重点。", "example": f"示例：我先说明当前情况，再说明{p}，最后确认下一步行动。"} for n,p in enumerate(principles[:3])], "exercise": f"请结合最近一次真实沟通，用上述三个方法重写一段至少 40 字的{focus}表达。"}
                task.setdefault("completedSteps", [0,1,2] if task["completed"] else [])
                task.setdefault("practicePassed", bool(task["completed"]))
            task.setdefault("completedSteps", [])
            task.setdefault("practiceAnswer", None)
            task.setdefault("practiceFeedback", None)
            task.setdefault("practicePassed", False)
            task.setdefault("practiceDegraded", False)
    if active and baseline and not any(t["actionType"] == "RETEST" for t in tasks):
        source = sources[baseline]
        tasks.append({"key":"retest", "day":2, "task":"按原场景条件复测，对比四维变化", "actionType":"RETEST", "sceneId":source["scene_id"], "sourceSessionId":baseline, "channel":source["channel"] or "TEXT", "depth":source["depth"] or "STANDARD", "completed":False, "completedAt":None, "evidence":None})
    return tasks
