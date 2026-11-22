"""两次训练对比：同场景比四维与逐轮，不同场景只比通用指标。"""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.infrastructure.llm import llm_gateway
from app.main import app

ANSWERS = [
    ("我在项目里负责接口开发，并解决了超时问题。", "负责接口开发"),
    ("我用压测结果验证了性能，并调整了缓存策略。", "压测结果验证了性能"),
    ("团队三个人分工明确，我负责后端接口与压测。", "调整了缓存策略"),
]


async def _fake_evaluation(_system_prompt: str, _user_prompt: str, **_kwargs):
    return {
        "scores": {"logic": 3, "appropriateness": 3, "correctness": 3, "relevance": 3, "concision": 3},
        "summary": "回答基本完整，细节还可以更具体。",
        "suggestions": [{"roundNo": 1, "problem": "细节不足", "original": "负责接口开发", "rewrite": "负责接口开发，并用压测数据说明效果。"}],
        "styleTags": ["待具体"],
        "evidence": [
            {"dimension": "logic", "roundNo": 1, "quote": "负责接口开发", "reason": "职责清楚。", "nextAction": "补充判断依据。"},
            {"dimension": "relevance", "roundNo": 2, "quote": "压测结果验证了性能", "reason": "正面回应问题。", "nextAction": "先给结论。"},
            {"dimension": "correctness", "roundNo": 3, "quote": "我负责后端接口与压测", "reason": "有个人贡献。", "nextAction": "补充量化结果。"},
            {"dimension": "concision", "roundNo": 2, "quote": "调整了缓存策略", "reason": "表达集中。", "nextAction": "再压缩一句。"},
        ],
    }


async def _fake_stream(_system_prompt, _messages):
    yield "能再具体说说你的角色吗？"


def _prepare(monkeypatch) -> None:
    monkeypatch.setattr(type(llm_gateway), "configured", property(lambda self: True))
    monkeypatch.setattr(llm_gateway, "complete_json", _fake_evaluation)
    monkeypatch.setattr(llm_gateway, "stream_text", _fake_stream)


def _run_session(client: TestClient, headers: dict, scene_id: str) -> str:
    created = client.post("/api/v1/training-sessions", headers=headers, json={"sceneId": scene_id})
    session_id = created.json()["data"]["id"]
    for answer, _quote in ANSWERS:
        response = client.post(
            f"/api/v1/training-sessions/{session_id}/messages", headers=headers, json={"content": answer}
        )
        assert response.status_code == 200
    finished = client.post(f"/api/v1/training-sessions/{session_id}/finish?create_plan=false", headers=headers)
    assert finished.status_code == 200
    return session_id


def test_comparison_scopes(monkeypatch) -> None:
    _prepare(monkeypatch)
    with TestClient(app, client=(f"cmp-{uuid4().hex}", 50000)) as client:
        registered = client.post("/api/v1/auth/register", json={
            "email": f"cmp-{uuid4().hex[:8]}@example.com",
            "password": "GraduateDesign123!",
            "displayName": "对比测试",
            "consent": True,
        })
        headers = {"Authorization": f"Bearer {registered.json()['data']['accessToken']}"}
        scenes = client.get("/api/v1/scenes", headers=headers).json()["data"]
        scene_a = scenes[0]["id"]
        scene_b = next(item["id"] for item in scenes if item["id"] != scene_a)

        first = _run_session(client, headers, scene_a)
        none = client.get(f"/api/v1/evaluations/{first}/comparison", headers=headers)
        assert none.status_code == 200
        assert none.json()["data"]["scope"] == "NONE"
        assert none.json()["data"]["previous"] is None

        second = _run_session(client, headers, scene_a)
        same = client.get(f"/api/v1/evaluations/{second}/comparison", headers=headers).json()["data"]
        assert same["scope"] == "SAME_SCENE"
        assert [row["key"] for row in same["dimensions"]] == ["logic", "relevance", "correctness", "concision"]
        assert same["dimensions"][0]["delta"] == 0
        assert same["metrics"], "同场景也要给出通用指标"
        assert same["rounds"], "同场景需要逐轮对比"
        assert same["summary"].startswith("本次与上一次同为")
        assert same["previous"]["sessionId"] == first

        third = _run_session(client, headers, scene_b)
        different = client.get(f"/api/v1/evaluations/{third}/comparison", headers=headers).json()["data"]
        assert different["scope"] == "DIFFERENT_SCENE"
        assert different["dimensions"] == []
        assert {row["key"] for row in different["metrics"]} == {
            "avgRoundLength", "avgSentenceLength", "fillerRate", "flagCount"
        }
        assert "题目与难度不同" in different["summary"]
        assert different["rounds"] == []


def test_comparison_rejects_other_users(monkeypatch) -> None:
    _prepare(monkeypatch)
    with TestClient(app, client=(f"cmp-{uuid4().hex}", 50000)) as client:
        first = client.post("/api/v1/auth/register", json={
            "email": f"cmp-a-{uuid4().hex[:8]}@example.com",
            "password": "GraduateDesign123!",
            "displayName": "甲",
            "consent": True,
        })
        headers_a = {"Authorization": f"Bearer {first.json()['data']['accessToken']}"}
        scene_id = client.get("/api/v1/scenes", headers=headers_a).json()["data"][0]["id"]
        session_id = _run_session(client, headers_a, scene_id)

        second = client.post("/api/v1/auth/register", json={
            "email": f"cmp-b-{uuid4().hex[:8]}@example.com",
            "password": "GraduateDesign123!",
            "displayName": "乙",
            "consent": True,
        })
        headers_b = {"Authorization": f"Bearer {second.json()['data']['accessToken']}"}
        assert client.get(f"/api/v1/evaluations/{session_id}/comparison", headers=headers_b).status_code == 404
