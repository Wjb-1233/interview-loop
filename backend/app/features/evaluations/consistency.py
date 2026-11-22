"""Validate public model checks and detect score/check contradictions."""


def validated_technical_checks(checks, turns) -> list[dict]:
    answers = {turn.round_no: turn.answer.content for turn in turns}
    result = []
    for item in checks:
        if not isinstance(item, dict) or item.get("verdict") not in {"CORRECT", "ERROR", "UNCERTAIN"}:
            continue
        quote, reason = item.get("quote"), item.get("reason")
        if isinstance(quote, str) and quote.strip() and isinstance(reason, str) and reason.strip() and quote in answers.get(item.get("roundNo"), ""):
            result.append({"roundNo": item["roundNo"], "quote": quote[:500],
                           "verdict": item["verdict"], "reason": reason[:1000]})
    return result[:4]


def score_conflicts(scores: dict, checks: list[dict]) -> list[dict]:
    if scores.get("logic", 0) < 5:
        return []
    return [{"roundNo": item["roundNo"], "quote": item["quote"],
             "reason": "专业核查标记为错误，但内容与逻辑为最高档，需要核对该错误的重要性与评分依据。"}
            for item in checks if item["verdict"] == "ERROR"]
