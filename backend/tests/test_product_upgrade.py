from tests.support.factories import model_response, client, register, finish, PLAN_DRAFT, make_docx
import json
import re
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.features.evaluations.objectives import completeness, question_type
from app.infrastructure.llm import llm_gateway
from app.main import app










def test_new_user_can_rewrite_without_scene(client):
    headers = register(client)
    response = client.post("/api/v1/scripts/generate", headers=headers, json={"objective": "说明项目贡献", "originalText": "我负责订单接口设计。", "extraContext": "应聘后端开发"})
    assert response.status_code == 201, response.text
    assert len(response.json()["data"]["versions"]) == 3
    assert all(item["sceneId"] is None for item in response.json()["data"]["versions"])


@pytest.mark.parametrize("channel", ["TEXT", "VOICE", "VIDEO"])
def test_preparation_shares_resume_jd_and_protects_ownership(client, channel):
    headers = register(client)
    text = "我负责毕业设计中的 Python 后端接口，使用 Redis 缓存热点订单，使用 MySQL 存储业务数据，并通过监控验证性能。"
    response = client.post("/api/v1/training-sessions/prepare", headers=headers, data={"sceneId": "scene-interview-03", "channel": channel, "depth": "THREE_LAYER", "duration": 5, "jd": "岗位要求熟悉 Python 后端开发、数据库设计与 Redis 缓存，能够分析性能问题。"}, files={"file": ("resume.docx", make_docx(text))})
    assert response.status_code == 201, response.text
    prepared = response.json()["data"]
    assert prepared["channel"] == channel
    assert prepared["depth"] == "THREE_LAYER"
    assert prepared["resumeFilename"] == "resume.docx"
    context = client.get(f"/api/v1/training-sessions/{prepared['id']}/interview-context", headers=headers)
    assert text in context.json()["data"]["instructions"]
    assert prepared["jdText"] in context.json()["data"]["instructions"]
    other = register(client)
    assert client.get(f"/api/v1/training-sessions/{prepared['id']}/interview-context", headers=other).status_code == 404
    if channel != "TEXT":
        saved = client.post("/api/v1/voice/sessions", headers=headers, data={"sceneId": "scene-interview-03", "preparedSessionId": prepared["id"], "channelHint": channel, "turns": json.dumps([{"question": "如何设计缓存", "answer": "我使用缓存减少重复查询"}, {"question": "如何验证", "answer": "对比延迟并检查一致性"}])})
        assert saved.status_code == 201, saved.text
        assert saved.json()["data"]["id"] == prepared["id"]
        current = client.get(f"/api/v1/training-sessions/{prepared['id']}", headers=headers).json()["data"]
        assert current["depth"] == "THREE_LAYER" and current["resumeFilename"] == "resume.docx"
        assert current["channel"] == channel


def test_plan_can_finish_and_retest_inherits_conditions(client):
    headers = register(client)
    baseline = client.post("/api/v1/training-sessions/prepare", headers=headers, data={"sceneId": "scene-interview-03", "depth": "PRESSURE"}).json()["data"]
    finish(client, headers, baseline["id"])
    plan = client.get("/api/v1/training-plans", headers=headers).json()["data"][0]
    assert [item["actionType"] for item in plan["tasks"]] == ["REPORT", "REWRITE", "COURSE", "RETEST"]
    prefix = f"/api/v1/training-plans/{plan['id']}/tasks"
    assert client.post(prefix + "/retest/complete", headers=headers, json={"evidence": baseline["id"]}).status_code == 422
    assert client.post(prefix + "/session-review/complete", headers=headers, json={}).status_code == 200
    rewritten = client.post(prefix + "/rewrite/complete", headers=headers, json={"evidence": "我负责订单接口设计，通过缓存减少重复查询，再用监控数据验证性能改善与一致性。"})
    assert rewritten.status_code == 200, rewritten.text
    assert rewritten.json()["data"]["tasks"][1]["completed"]
    assert client.post(prefix + "/course/course/complete", headers=headers).status_code == 422
    for index in range(3):
        assert client.post(prefix + f"/course/steps/{index}/complete", headers=headers).status_code == 200
    learned = client.post(prefix + "/course/course/complete", headers=headers).json()["data"]
    assert learned["tasks"][2]["learned"] and not learned["tasks"][2]["completed"]
    practiced = client.post(prefix + "/course/practice", headers=headers, json={"answer": "我的结论是先处理客户反馈的问题，依据是本周三位客户都提到同一处报错，我今天下午提交修复方案并同步验证结果。"})
    assert practiced.status_code == 200, practiced.text
    retest = client.post("/api/v1/training-sessions/prepare", headers=headers, data={"sceneId": baseline["sceneId"], "planId": plan["id"], "taskKey": "retest", "depth": "STANDARD", "channel": "VIDEO"})
    assert retest.status_code == 201, retest.text
    current = retest.json()["data"]
    assert current["channel"] == "TEXT" and current["depth"] == "PRESSURE"
    finish(client, headers, current["id"])
    completed = client.post(prefix + "/retest/complete", headers=headers, json={"evidence": current["id"]})
    assert completed.status_code == 200, completed.text
    result = completed.json()["data"]
    assert result["status"] == "COMPLETED" and result["progress"] == 100
    assert result["comparison"]["baselineSessionId"] == baseline["id"]
    assert result["comparison"]["retestSessionId"] == current["id"]
    assert len(client.get("/api/v1/training-plans", headers=headers).json()["data"]) == 1


def test_knowledge_question_does_not_require_project_story():
    assert question_type("解释索引的原理和适用边界") == "KNOWLEDGE"
    assert completeness(["索引是用于定位数据的结构，通过有序组织减少扫描，例如范围查询，但是需要考虑更新代价。"], ["解释索引的原理和适用边界"]) == 1


def test_reports_do_not_compare_different_intensities(client):
    headers = register(client)
    for depth in ["STANDARD", "PRESSURE"]:
        created = client.post("/api/v1/training-sessions/prepare", headers=headers, data={"sceneId": "scene-interview-03", "depth": depth}).json()["data"]
        finish(client, headers, created["id"])
    report = client.get(f"/api/v1/evaluations/{created['id']}", headers=headers).json()["data"]
    assert report["previousScores"] is None
    assert report["previousOverall"] is None


def test_dashboard_excludes_fallback_scores_and_filters_channels(client, monkeypatch):
    headers = register(client)
    first = client.post("/api/v1/training-sessions/prepare", headers=headers, data={"sceneId": "scene-interview-03"}).json()["data"]
    finish(client, headers, first["id"])

    async def unavailable(*args, **kwargs):
        raise RuntimeError("offline evaluation")

    monkeypatch.setattr(llm_gateway, "complete_json", unavailable)
    second = client.post("/api/v1/training-sessions/prepare", headers=headers, data={"sceneId": "scene-interview-03"}).json()["data"]
    finish(client, headers, second["id"])
    data = client.get("/api/v1/dashboard", headers=headers).json()["data"]
    assert data["trainingCount"] == 2
    assert data["formalEvaluationCount"] == 1
    assert len(data["trends"]) == 1
    filtered = client.get("/api/v1/dashboard?channel=VIDEO", headers=headers).json()["data"]
    assert filtered["trends"] == []
