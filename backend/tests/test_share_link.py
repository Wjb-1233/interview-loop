"""教练查看链接：只读、可批注、过期与篡改都拒绝。"""

import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


def _register(client: TestClient, prefix: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": f"{prefix}-{uuid4().hex[:8]}@example.com", "password": "GraduateDesign123!", "displayName": "分享", "consent": True},
    )
    return {"Authorization": f"Bearer {response.json()['data']['accessToken']}"}


def _finished_session(client: TestClient, headers: dict[str, str]) -> str:
    scene = client.get("/api/v1/scenes", headers=headers).json()["data"][0]["id"]
    sid = client.post("/api/v1/training-sessions", headers=headers, json={"sceneId": scene}).json()["data"]["id"]
    for index in range(2):
        client.post(
            f"/api/v1/training-sessions/{sid}/messages/complete",
            headers=headers,
            json={"content": f"第{index + 1}轮：先说结论，再补依据。"},
        )
    assert client.post(f"/api/v1/training-sessions/{sid}/finish?create_plan=false", headers=headers).status_code == 200
    return sid


def test_share_link_is_read_only_and_annotatable() -> None:
    with TestClient(app, client=(f"share-{uuid4().hex}", 50040)) as client:
        headers = _register(client, "share")
        session_id = _finished_session(client, headers)

        created = client.post(f"/api/v1/share/training-sessions/{session_id}", headers=headers)
        assert created.status_code == 200
        url = created.json()["data"]["url"]
        token = url.rsplit("/", 1)[-1]
        api_url = f"/api/v1/share/{token}"

        opened = client.get(api_url)
        assert opened.status_code == 200
        payload = opened.json()["data"]
        assert payload["overallScore"] is not None
        assert "recordingUrl" in payload

        annotated = client.post(f"{api_url}/annotations", json={"atMs": 1200, "comment": "开场缺少结论", "author": "教练"})
        assert annotated.status_code == 200
        assert len(annotated.json()["data"]["annotations"]) == 1

        again = client.get(api_url).json()["data"]
        assert again["annotations"][0]["comment"] == "开场缺少结论"
        # 链接只读：不存在改分的入口
        assert client.patch(api_url, json={"overallScore": 100}).status_code in {404, 405}


def test_share_link_rejects_other_user_and_tampering() -> None:
    with TestClient(app, client=(f"share-{uuid4().hex}", 50041)) as client:
        owner = _register(client, "owner")
        stranger = _register(client, "stranger")
        session_id = _finished_session(client, owner)

        assert client.post(f"/api/v1/share/training-sessions/{session_id}", headers=stranger).status_code == 404
        url = client.post(f"/api/v1/share/training-sessions/{session_id}", headers=owner).json()["data"]["url"]
        token = url.rsplit("/", 1)[-1]

        tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")
        assert client.get(f"/api/v1/share/{tampered}").status_code == 404


def test_expired_share_link_is_gone() -> None:
    from app.features.share.router import issue_token

    with TestClient(app, client=(f"share-{uuid4().hex}", 50042)) as client:
        headers = _register(client, "expire")
        session_id = _finished_session(client, headers)
        token, _ = issue_token(session_id, ttl=-1)
        response = client.get(f"/api/v1/share/{token}")
        assert response.status_code == 410
        assert response.json()["title"] == "SHARE_EXPIRED"

def _share_token(client: TestClient, headers: dict[str, str], session_id: str) -> str:
    url = client.post(f"/api/v1/share/training-sessions/{session_id}", headers=headers).json()["data"]["url"]
    return url.rsplit("/", 1)[-1]


def _store_delivery(session_id: str, delivery: dict) -> None:
    async def run() -> None:
        from app.db.base import session_factory
        from app.db.models import TrainingSession

        async with session_factory() as db:
            training = await db.get(TrainingSession, session_id)
            training.delivery = delivery
            await db.commit()

    asyncio.run(run())


def test_text_session_share_has_transcript() -> None:
    """文字训练结束不写 delivery.transcript，分享页也要能看到逐轮问答。"""
    with TestClient(app, client=(f"share-{uuid4().hex}", 50043)) as client:
        headers = _register(client, "textshare")
        session_id = _finished_session(client, headers)
        token = _share_token(client, headers, session_id)

        payload = client.get(f"/api/v1/share/{token}").json()["data"]
        transcript = payload["transcript"]
        assert len(transcript) == 2, transcript
        assert [item["roundNo"] for item in transcript] == [1, 2]
        assert transcript[0]["text"] == "第1轮：先说结论，再补依据。"
        assert transcript[1]["text"] == "第2轮：先说结论，再补依据。"
        assert all(item["question"] for item in transcript)
        assert all(item["edited"] is False for item in transcript)
        assert all(item["startMs"] is None and item["confidence"] is None for item in transcript)

        # 与打印版报告同一批轮次
        report = client.get(f"/api/v1/share/{token}/report")
        assert "第 1 题" in report.text
        assert "第 2 题" in report.text


def _mark_review_required(session_id: str) -> float:
    """造一场矛盾未消解的评分：库内保留原总分（这里直接写成 100），只翻标记位。"""

    async def run() -> float:
        from sqlalchemy import select
        from app.db.base import session_factory
        from app.db.models import Evaluation

        async with session_factory() as db:
            row = await db.scalar(select(Evaluation).where(Evaluation.session_id == session_id))
            original = row.overall_score
            row.overall_score = 100.0
            row.review_required = True
            await db.commit()
            return original

    return asyncio.run(run())


def test_review_required_hides_overall_score_in_share_and_report() -> None:
    """矛盾未消解：分享接口与打印版都不出现库内总分，只给原因；四维留作参考。"""
    with TestClient(app, client=(f"share-{uuid4().hex}", 50045)) as client:
        headers = _register(client, "review")
        session_id = _finished_session(client, headers)
        assert _mark_review_required(session_id) != 100.0
        token = _share_token(client, headers, session_id)

        payload = client.get(f"/api/v1/share/{token}").json()["data"]
        assert payload["overallScore"] is None
        assert "矛盾" in payload["scoreUnavailableReason"] and "暂不可用" in payload["scoreUnavailableReason"]
        assert all(payload["scores"][key] is not None for key in ("logic", "relevance", "correctness", "concision"))

        printed = client.get(f"/api/v1/share/{token}/report")
        assert printed.status_code == 200
        assert "100.0" not in printed.text and "<b>100" not in printed.text
        assert "暂不可用" in printed.text
        assert payload["scoreUnavailableReason"] in printed.text
        assert "四维分值为原记录值，仅作参考" in printed.text
        # 四维也照常印出，只是标注为参考
        assert f'<td class="num">{payload["scores"]["logic"]}</td>' in printed.text


def test_share_prefers_stored_transcript() -> None:
    """已有 transcript（视频任务或人工修正写入）时保持原样，不回退到消息表。"""
    with TestClient(app, client=(f"share-{uuid4().hex}", 50044)) as client:
        headers = _register(client, "storedshare")
        session_id = _finished_session(client, headers)
        stored = [
            {
                "roundNo": 9,
                "question": "修正后的问题",
                "text": "修正后的回答",
                "startMs": 0,
                "endMs": 1200,
                "confidence": 0.9,
                "edited": True,
            }
        ]
        _store_delivery(session_id, {"transcript": stored})
        token = _share_token(client, headers, session_id)

        payload = client.get(f"/api/v1/share/{token}").json()["data"]
        assert payload["transcript"] == stored
