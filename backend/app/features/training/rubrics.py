"""Versioned interview criteria, snapshotted when a new attempt is created."""
import copy
import re
import hashlib
import json

VERSION = "interview-2026-11-v1"

BACKEND_CRITERIA = [
    {"id": "project", "name": "工程判断与本人贡献", "match": "项目|决策|负责|取舍",
     "question": "请说明一个你亲自参与的技术决策，以及判断它有效的依据。",
     "points": ["本人职责", "选择依据", "验证方法", "风险边界"],
     "probes": ["这部分具体由你完成什么，与团队其他人的职责如何区分？", "你比较过哪些方案，为什么选择现在这一种？", "如何验证改动有效，基线与测试条件分别是什么？", "这种做法有哪些限制，失败后如何处理？"],
     "alternatives": ["没有量化数据时可说明可核对的现象与验证步骤", "可以明确说明未实际验证的部分"],
     "mistakes": ["将团队成果全部归为本人贡献", "没有验证条件就断言方案普遍有效"]},
    {"id": "transaction", "name": "事务与并发边界", "match": "事务|隔离|并发|幂等|库存|核销",
     "question": "并发修改同一份业务数据时，你如何保障一致性并验证边界？",
     "points": ["业务不变量", "并发控制机制", "适用条件与代价", "并发验证"],
     "probes": ["这项业务必须保持的约束是什么？", "具体依靠什么机制保证并发操作符合约束？", "方案在什么条件下成立，有哪些代价或限制？", "你会如何设计并发测试，确认失败重试也不会破坏约束？"],
     "alternatives": ["锁、条件更新、唯一约束等方案可按业务条件组合", "应说明数据库隔离级别与事务边界"],
     "mistakes": ["把幂等与所有一致性问题等同", "不说明条件就保证任何并发场景都正确"],
     "referenceUrl": "https://dev.mysql.com/doc/refman/8.4/en/innodb-transaction-isolation-levels.html"},
    {"id": "cache", "name": "缓存一致性与方案取舍", "match": "缓存|Redis|redis",
     "question": "引入缓存后，你如何处理数据变化和一致性要求？",
     "points": ["一致性要求", "更新与失效流程", "失败与并发边界", "效果验证"],
     "probes": ["这项业务可以接受怎样的数据延迟，为什么？", "数据库与缓存分别在什么时候更新或失效？", "并发更新或失效失败时会发生什么，你如何处理？", "你会观察哪些指标，并怎样验证缓存方案的效果？"],
     "alternatives": ["根据业务接受程度讨论不同一致性策略", "可以选择不使用缓存并解释取舍"],
     "mistakes": ["把所有业务默认当作允许短暂不一致", "只说性能提升而不说明失效与失败路径"]},
    {"id": "diagnosis", "name": "故障定位与验证", "match": "故障|超时|定位|排查|变慢|监控|索引",
     "question": "接口突然变慢时，你如何定位范围、验证原因并处理风险？",
     "points": ["影响范围", "定位证据", "止损与取舍", "修复验证"],
     "probes": ["先确认哪些接口、用户和时间范围受到影响？", "你会用哪些日志、指标或实验区分可能原因？", "什么情况下先止损，如何选择回滚或其他措施？", "如何验证修复有效，并确认没有引入新的问题？"],
     "alternatives": ["区分真实处理经历和计划采用的方法", "根据故障影响说明定位与止损的先后关系"],
     "mistakes": ["没有证据就直接归因", "用一次波动证明某个改动一定有效"]},
]


def profile_for(scene, bank: list[dict]) -> list[dict]:
    custom = []
    for index, item in enumerate(bank):
        rubric = item.get("rubric")
        if not isinstance(rubric, dict) or not rubric.get("requiredPoints"):
            continue
        points = rubric["requiredPoints"][:8]
        custom.append({"id": f"question-{index + 1}", "name": rubric.get("competency") or item.get("dimension") or f"考察点 {index + 1}",
                       "question": item["text"], "match": re.escape(item["text"][:8]), "points": points,
                       "probes": [f"关于“{point}”，请说明你的具体依据或验证方法。" for point in points],
                       "alternatives": rubric.get("acceptableVariants", []), "mistakes": rubric.get("commonMistakes", []),
                       "version": rubric.get("version", "v1"), "reviewed": rubric.get("reviewed", False),
                       "referenceUrl": rubric.get("referenceUrl")})
        custom[-1]["transferQuestions"] = rubric.get("transferQuestions", [])
    if custom:
        return custom
    if scene.category not in {"技术一面", "技术二面 / 复面", "交叉面 / 总监面"} or not re.search(r"后端|Backend|backend", scene.position):
        return []
    from app.features.training.question_catalog import transfer_specs, CATALOG_VERSION
    criteria = copy.deepcopy(BACKEND_CRITERIA)
    for criterion in criteria:
        criterion.update(transferQuestionSpecs=transfer_specs(criterion['id']),
                         catalogVersion=CATALOG_VERSION, reviewed=False)
    return criteria


def new_context(scene, bank: list[dict], enabled: bool = False) -> dict:
    from app.features.evaluations.standards import current_standard
    standard = current_standard()
    criteria = profile_for(scene, bank)
    rubric_version = hashlib.sha256(json.dumps({"criteria": criteria, "scoringStandard": standard["hash"]}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    return {"version": VERSION, "rubricVersion": rubric_version, "purpose": "PRACTICE", "adaptiveEnabled": bool(enabled and criteria),
            "criteria": criteria, "scoringStandard": standard, "evidenceTrace": [], "coverage": {}, "hintUses": 0}


def fresh_context(template: dict | None) -> dict:
    """Keep the frozen rubric, never copy evidence or assistance from another attempt."""
    source = template or {}
    result = {"version": source.get("version", VERSION), "rubricVersion": source.get("rubricVersion", "legacy"),
            "purpose": "PRACTICE", "adaptiveEnabled": bool(source.get("adaptiveEnabled")),
            "criteria": copy.deepcopy(source.get("criteria", [])),
            "evidenceTrace": [], "coverage": {}, "hintUses": 0}
    if "scoringStandard" in source:
        result["scoringStandard"] = copy.deepcopy(source["scoringStandard"])
    return result


def criteria_instructions(context: dict | None) -> str:
    criteria = (context or {}).get("criteria", [])
    if not criteria or not (context or {}).get("adaptiveEnabled"):
        return ""
    topics = "；".join(f"{item['name']}：{'、'.join(item['points'])}" for item in criteria)
    return ("\n本场按回答证据追问。考察点：" + topics +
            "。先辨别本人行动、依据和未验证部分；已解释的内容不重复问，优先追问缺口，单个考察点最多追问两次。"
            "对前后陈述差异先确认条件，不指责造假；说明未知并提出验证方法不等于回避。每轮只问一个聚焦问题。")
