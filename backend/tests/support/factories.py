import json
import re
from uuid import uuid4
from io import BytesIO
from zipfile import ZipFile
import pytest
from fastapi.testclient import TestClient
from app.infrastructure.llm import llm_gateway
from app.main import app
from app.features.evaluations.scoring import SYSTEM_PROMPT as EVALUATION_PROMPT
from app.features.plans.service import PRACTICE_PROMPT, REWRITE_PROMPT
from app.features.plans.generation import SYSTEM_PROMPT as PLAN_PROMPT
from app.features.scripts.service import SYSTEM_PROMPT as SCRIPT_PROMPT

PLAN_DRAFT = {
    "title": "逻辑性专项提升：先复盘再学微课",
    "lesson": {
        "title": "逻辑性微课",
        "intro": "用三个步骤让回答先有结论，再有依据，最后落到行动。",
        "steps": [
            {
                "title": "先给结论",
                "explanation": "开口第一句先说结论，让对方立刻知道你要回答什么。",
                "example": "我的结论是：先解决客户反馈的这个问题。",
            },
            {
                "title": "再给依据",
                "explanation": "用一条可核对的事实支撑结论，不堆形容词。",
                "example": "依据是本周三位客户都提到同一处报错。",
            },
            {
                "title": "落到行动",
                "explanation": "明确谁在什么时候做什么，避免空泛表态。",
                "example": "我今天下午提交方案，明天在群里同步结果。",
            },
        ],
        "exercise": "结合最近一次真实沟通，用上面三个方法重写一段至少 40 字的逻辑性表达。",
    },
    "practice_task": "回到逻辑性基础场景完成至少 6 轮对话，重点练习结论先行。",
    "rewrite_task": "对照逐轮批注，挑选问题最大的回答重新组织表达。",
    "retest_task": "回到原场景完成新一轮训练，对比逻辑性评分变化。",
}


def make_docx(text: str) -> bytes:
    data = BytesIO()
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    with ZipFile(data, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{escaped}</w:t></w:r></w:p></w:body></w:document>",
        )
    return data.getvalue()


async def model_response(system: str, prompt: str, **kwargs):
    if system in (REWRITE_PROMPT, PRACTICE_PROMPT):
        return {"passed": True, "feedback": "回答补上了真实行动与验证结果，回应了本题要求。"}
    if system == SCRIPT_PROMPT:
        return {"versions": [{"style": style, "content": "我负责订单接口设计，通过缓存减少重复查询。", "highlights": ["事实具体"]} for style in ["正式", "亲和", "简洁"]]}
    if system == EVALUATION_PROMPT:
        turn = re.search(r"第 (\d+) 轮用户：([^\n]+)", prompt)
        evidence = [dict(dimension=key, roundNo=int(turn[1]), quote=turn[2][:120], reason="原话给出了具体行动。", nextAction="补充可核验的验证结果。") for key in ["logic", "relevance", "correctness", "concision"]] if turn else []
        return {"scores": {key: 3 for key in ["logic", "relevance", "correctness", "concision"]}, "summary": "表达清楚，仍可补充依据。", "suggestions": [{"roundNo": 1, "original": "我负责", "problem": "补充结果", "rewrite": "补上验证过程与真实结果"}], "styleTags": ["直接"], "evidence": evidence}
    if system == PLAN_PROMPT:
        return PLAN_DRAFT
    if "只根据简历" in system:
        return {"question": "你负责的缓存项目如何验证结果？"}
    return {"plan": [{"text": "请介绍岗位相关的缓存项目经历", "dimension": "信息完整", "difficulty": "中级"}]}


@pytest.fixture
def client(monkeypatch):
    async def stream(*args, **kwargs):
        yield "你如何验证项目方案的实际结果？"
    monkeypatch.setattr(type(llm_gateway), "configured", property(lambda self: True))
    monkeypatch.setattr(llm_gateway, "complete_json", model_response)
    monkeypatch.setattr(llm_gateway, "stream_text", stream)
    with TestClient(app, client=(f"upgrade-{uuid4().hex}", 51000)) as value:
        yield value


def register(client):
    result = client.post("/api/v1/auth/register", json={"email": f"upgrade-{uuid4().hex}@example.com", "password": "UpgradeTest123!", "displayName": "升级验收", "consent": True})
    assert result.status_code == 201
    return {"Authorization": f"Bearer {result.json()['data']['accessToken']}"}


def finish(client, headers, session_id, rounds=6):
    for _ in range(rounds):
        response = client.post(f"/api/v1/training-sessions/{session_id}/messages/complete", headers=headers, json={"content": "我负责订单系统的接口设计，先分析重复查询，再实现缓存，通过监控验证延迟降低，并检查一致性边界。"})
        assert response.status_code == 200, response.text
    response = client.post(f"/api/v1/training-sessions/{session_id}/finish", headers=headers)
    assert response.status_code == 200, response.text

