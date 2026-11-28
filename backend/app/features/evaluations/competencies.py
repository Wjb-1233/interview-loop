"""Validate role-specific assessment against this attempt's rubric and quotes."""
import copy
import re


def _verified_evidence(draft: dict, by_round: dict, matched: set) -> list[dict]:
    """只保留逐字出现在对应回答里的引用。"""
    raw_evidence = draft.get("evidence") if isinstance(draft.get("evidence"), list) else []
    evidence = []
    for item in raw_evidence[:4]:
        if not isinstance(item, dict):
            continue
        turn = by_round.get(item.get("roundNo"))
        quote = item.get("quote")
        if turn and turn.round_no in matched and isinstance(quote, str) and len(quote.strip()) >= 4 and quote in turn.answer.content:
            evidence.append({"roundNo": turn.round_no, "quote": quote[:500], "answerMessageId": turn.answer.id})
    return evidence


def _competency_status(draft: dict, matched: set, evidence: list, missing: list, technical_checks: list) -> str:
    if evidence and any(isinstance(check, dict) and check.get("verdict") in {"ERROR", "UNCERTAIN"}
                        and check.get("roundNo") in matched for check in technical_checks):
        return "UNCERTAIN"
    if evidence and draft.get("status") == "UNCERTAIN":
        return "UNCERTAIN"
    if evidence and not missing and draft.get("status") == "DEMONSTRATED":
        return "DEMONSTRATED"
    return "NOT_COVERED" if not matched else "LIMITED"


def _matrix_entry(criterion: dict, context: dict, trace: list, turns: list, by_round: dict, payload) -> dict:
    matched = {turn.round_no for turn in turns if re.search(criterion.get("match", "^$"), turn.question.content)}
    matched.update(item["roundNo"] for item in trace if item.get("criterionId") == criterion["id"])
    draft = next((item for item in payload.professional_matrix if isinstance(item, dict) and item.get("competencyId") == criterion["id"]), {})
    evidence = _verified_evidence(draft, by_round, matched)
    points = criterion["points"]
    raw_points = draft.get("metPoints") if isinstance(draft.get("metPoints"), list) else []
    met = [point for point in points if point in raw_points] if evidence else []
    missing = [point for point in points if point not in met]
    status = _competency_status(draft, matched, evidence, missing, payload.technical_checks)
    reason = draft.get("reason") if evidence else None
    return {"competencyId": criterion["id"], "name": criterion["name"], "status": status,
            "expectedPoints": points, "metPoints": met, "missingPoints": missing,
            "evidence": evidence, "reason": str(reason)[:600] if reason else ("本场尚未考察这一项。" if not matched else "已有相关回答，仍需补充可核对的专业要点依据。"),
            "rubricVersion": criterion.get("version", context.get("version", "v1")),
            "reviewed": bool(criterion.get("reviewed", False)), "referenceUrl": criterion.get("referenceUrl")}


def _transfer_result(transfer: dict, matrix: list, turns: list, conflicts: list) -> str:
    target = [item for item in matrix if item["competencyId"] in transfer.get("competencies", [])]
    if len(turns) < 2:
        return "INSUFFICIENT_SAMPLE"
    if conflicts:
        return "AWAITING_REVIEW"
    if target and all(item["status"] == "DEMONSTRATED" for item in target):
        return "INDEPENDENT_APPLICATION"
    return "NEEDS_PRACTICE"


def assessment_snapshot(payload, training, turns, conflicts, model: str) -> dict:
    from app.features.evaluations.standards import standard_metadata
    context = training.assessment_context or {}
    trace = context.get("evidenceTrace", [])
    by_round = {turn.round_no: turn for turn in turns}
    matrix = [_matrix_entry(criterion, context, trace, turns, by_round, payload) for criterion in context.get("criteria", [])]
    transfer = copy.deepcopy(context.get("transfer"))
    if transfer:
        transfer["result"] = _transfer_result(transfer, matrix, turns, conflicts)
        transfer["answeredRounds"] = len(turns)
        transfer["note"] = "仅针对本次新题与参考要点的模型判断，不与原题分数直接连线。"
    return {"version": context.get("version", "interview-2026-11-v1"), "model": model,
            "scoringStandard": standard_metadata(context),
            "rubricVersion": context.get("rubricVersion", "legacy"), "purpose": context.get("purpose", "PRACTICE"),
            "hintUses": int(context.get("hintUses", 0)), "professionalMatrix": matrix,
            "evidenceTrace": copy.deepcopy(trace), "consistencyConflicts": conflicts,
            "transfer": transfer}
