"""提示卡：给出结构与关键词，不泄露完整答案。"""

import asyncio
import uuid

from fastapi.testclient import TestClient


def _headers(client: TestClient) -> dict:
    email = f"hint-{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "HintTest123!", "displayName": "提示", "consent": True},
    )
    return {"Authorization": f"Bearer {reg.json()['data']['accessToken']}"}


def test_hint_returns_question_structure_and_keywords() -> None:
    from app.main import app

    with TestClient(app) as client:
        headers = _headers(client)
        scene = client.get("/api/v1/scenes?size=1", headers=headers).json()["data"][0]
        created = client.post(
            "/api/v1/training-sessions", json={"sceneId": scene["id"]}, headers=headers
        ).json()["data"]

        response = client.post(f"/api/v1/training-sessions/{created['id']}/hint", headers=headers)
        assert response.status_code == 200, response.text
        hint = response.json()["data"]
        assert hint["question"]
        assert 3 <= len(hint["structure"]) <= 4
        assert hint["keywords"]
        assert any("不要背答案" in tip for tip in hint["tips"])

# 场景固定标签（岗位/面试轮次/JD 标签）——「增长」既在标签里也在题目里，不参与计数
SCENE_LABELS = ("移动互联网产品经理", "交叉面/总监面", "猎聘 JD", "产品经理")
GROWTH_QUESTION = "增长和留存冲突时你怎么取舍？"


def label_count(keywords: list[str]) -> int:
    """关键词里来自场景固定标签的个数（「增长」这类题目里也有的词不算标签兜底）。"""
    return len([word for word in keywords if word in SCENE_LABELS])


async def _append_question(session_id: str, question: str) -> None:
    """把待测问题写成最后一条 AI 消息，提示卡据此生成关键词。"""

    from app.db.base import session_factory
    from app.db.models import Message

    async with session_factory() as db:
        db.add(Message(session_id=session_id, round_no=1, speaker="AI", content=question))
        await db.commit()


def _growth_session(client: TestClient, headers: dict) -> str:
    scene = next(
        item for item in client.get("/api/v1/scenes?size=100", headers=headers).json()["data"]
        if item["id"] == "scene-jd-product"
    )
    created = client.post(
        "/api/v1/training-sessions", json={"sceneId": scene["id"]}, headers=headers
    ).json()["data"]
    asyncio.run(_append_question(created["id"], GROWTH_QUESTION))
    return created["id"]


def test_hint_keywords_follow_question_and_skip_scene_label_noise() -> None:
    """关键词来自题目，场景固定标签最多兜底 2 个，且不出现被截断的残词。"""

    from app.main import app

    with TestClient(app) as client:
        headers = _headers(client)
        session_id = _growth_session(client, headers)

        response = client.post(f"/api/v1/training-sessions/{session_id}/hint", headers=headers)
        assert response.status_code == 200, response.text
        hint = response.json()["data"]

        keywords = hint["keywords"]
        # 题目关键词优先：至少 3 个直接出现在题目里
        assert len([word for word in keywords if word in GROWTH_QUESTION]) >= 3
        # 场景固定标签只兜底，不被岗位标签占满
        assert label_count(keywords) <= 2
        assert len(keywords) <= 6
        # 截断残词（旧实现取中文 2-6 字时的产物）不再出现
        assert "增长和留存冲" not in keywords
        assert all(not word.startswith("增长和留存冲") for word in keywords)
        assert all(len(word) >= 2 for word in keywords)
        assert keywords == ["增长", "留存冲突", "取舍", "移动互联网产品经理", "交叉面/总监面"]
        # 命中维度（题库里带维度）时关键词与结构仍贴着该维度：这道题要求比较取舍
        assert hint["dimension"] == "内容与逻辑"
        assert "取舍" in keywords
        assert any("取舍" in item for item in hint["structure"])


def test_hint_keywords_degrade_without_llm_and_for_english_question() -> None:
    """LLM 不可用与英文题目都走纯规则兜底：不崩、不空、不堆场景标签。"""

    from app.core.config import settings
    from app.features.training.hint_keywords import build_hint_keywords

    # 提示卡是纯规则路径（测试环境 LLM_API_KEY 为空即降级态），这里确认前提成立
    assert not settings.llm_api_key

    english = build_hint_keywords(
        "Tell me about a time you handled a conflict with a teammate.",
        dimension="内容与逻辑",
        scene_terms=list(SCENE_LABELS),
    )
    assert english[:3] == ["handled", "conflict", "teammate"]
    assert label_count(english) <= 2

    # 题目切不出关键词时才轮到维度词与场景标签，且场景标签依旧最多 2 个
    sparse = build_hint_keywords("你怎么取舍？", dimension="信息完整", scene_terms=list(SCENE_LABELS))
    assert sparse[:2] == ["取舍", "背景"]
    assert label_count(sparse) <= 2

    assert build_hint_keywords("", scene_terms=[]) == []
    assert len(build_hint_keywords("", scene_terms=list(SCENE_LABELS))) == 2
