"""Validate role-specific assessment against this attempt's rubric and quotes."""
import copy
import re


def assessment_snapshot(payload, training, turns, conflicts, model: str) -> dict:
    context = training.assessment_context or {}
    trace = context.get("evidenceTrace", [])
    by_round = {turn.round_no: turn for turn in turns}
    matrix = []
    for criterion in context.get("criteria", []):
        matched = {turn.round_no for turn in turns if re.search(criterion.get("match", "^$"), turn.question.content)}
        matched.update(item["roundNo"] for item in trace if item.get("criterionId") == criterion["id"])
        draft = next((item for item in payload.professional_matrix if isinstance(item, dict) and item.get("competencyId") == criterion["id"]), {})
        evidence = []
        raw_evidence = draft.get("evidence") if isinstance(draft.get("evidence"), list) else []
        for item in raw_evidence[:4]:
            if not isinstance(item, dict):
                continue
            turn = by_round.get(item.get("roundNo"))
            quote = item.get("quote")
            if turn and turn.round_no in matched and isinstance(quote, str) and len(quote.strip()) >= 4 and quote in turn.answer.content:
                evidence.append({"roundNo": turn.round_no, "quote": quote[:500], "answerMessageId": turn.answer.id})
        points = criterion["points"]
        raw_points = draft.get("metPoints") if isinstance(draft.get("metPoints"), list) else []
        met = [point for point in points if point in raw_points] if evidence else []
        missing = [point for point in points if point not in met]
        status = "NOT_COVERED" if not matched else "LIMITED"
        if evidence and draft.get("status") == "UNCERTAIN":
            status = "UNCERTAIN"
        elif evidence and not missing and draft.get("status") == "DEMONSTRATED":
            status = "DEMONSTRATED"
        if evidence and any(isinstance(check, dict) and check.get("verdict") in {"ERROR", "UNCERTAIN"}
                            and check.get("roundNo") in matched for check in payload.technical_checks):
            status = "UNCERTAIN"
        reason = draft.get("reason") if evidence else None
        matrix.append({"competencyId": criterion["id"], "name": criterion["name"], "status": status,
                       "expectedPoints": points, "metPoints": met, "missingPoints": missing,
                       "evidence": evidence, "reason": str(reason)[:600] if reason else ("本场尚未考察这一项。" if not matched else "已有相关回答，仍需补充可核对的专业要点依据。"),
                       "rubricVersion": criterion.get("version", context.get("version", "v1")),
                       "reviewed": bool(criterion.get("reviewed", False)), "referenceUrl": criterion.get("referenceUrl")})
    transfer = copy.deepcopy(context.get("transfer"))
    if transfer:
        target = [item for item in matrix if item["competencyId"] in transfer.get("competencies", [])]
        transfer["result"] = "INSUFFICIENT_SAMPLE" if len(turns) < 2 else "AWAITING_REVIEW" if conflicts else "INDEPENDENT_APPLICATION" if target and all(item["status"] == "DEMONSTRATED" for item in target) else "NEEDS_PRACTICE"
        transfer["answeredRounds"] = len(turns)
        transfer["note"] = "仅针对本次新题与参考要点的模型判断，不与原题分数直接连线。"
    return {"version": context.get("version", "interview-2026-11-v1"), "model": model,
            "rubricVersion": context.get("rubricVersion", "legacy"), "purpose": context.get("purpose", "PRACTICE"),
            "hintUses": int(context.get("hintUses", 0)), "professionalMatrix": matrix,
            "evidenceTrace": copy.deepcopy(trace), "consistencyConflicts": conflicts,
            "transfer": transfer}
