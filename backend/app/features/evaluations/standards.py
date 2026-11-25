"""Freeze the actual scoring instructions used by each new interview attempt."""
import copy
import hashlib

STANDARD_ID = "expression-2026-11-25-v1"
DIMENSION_LABELS = {"logic": "内容与逻辑", "relevance": "贴合问题", "correctness": "信息完整", "concision": "表达干净"}


def current_standard() -> dict:
    from app.features.evaluations.scoring import SYSTEM_PROMPT

    return {"id": STANDARD_ID, "scale": {"min": 1, "max": 5, "integer": True},
            "dimensions": dict(DIMENSION_LABELS),
            "scope": "中文面试表达；专业内容按场景考察点核查，不预测招聘结果。",
            "hash": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
            "systemPrompt": SYSTEM_PROMPT,
            "humanCalibration": "PENDING", "effectiveFrom": "2026-11-25"}


def scoring_prompt(context: dict | None) -> str:
    frozen = (context or {}).get("scoringStandard")
    if isinstance(frozen, dict) and isinstance(frozen.get("systemPrompt"), str):
        return frozen["systemPrompt"]
    from app.features.evaluations.scoring import SYSTEM_PROMPT
    return SYSTEM_PROMPT


def standard_metadata(context: dict | None) -> dict:
    frozen = (context or {}).get("scoringStandard")
    if not isinstance(frozen, dict):
        return {"id": "legacy-unversioned", "humanCalibration": "UNKNOWN"}
    return copy.deepcopy({key: value for key, value in frozen.items() if key != "systemPrompt"})
