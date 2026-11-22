"""0 轮占位会话：列表不展示，兜底脚本只删真正的空场次。"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.base import session_factory
from app.db.models import Message, TrainingSession
from scripts.cleanup_empty_sessions import run as cleanup_run
from tests.support.factories import client, register


def prepare(client, headers):
    response = client.post(
        '/api/v1/training-sessions/prepare',
        headers=headers,
        data={'sceneId': 'scene-interview-03', 'channel': 'TEXT'},
    )
    assert response.status_code == 201, response.text
    return response.json()['data']['id']


def mutate(session_id, **changes):
    async def apply():
        async with session_factory() as db:
            training = await db.get(TrainingSession, session_id)
            for key, value in changes.items():
                setattr(training, key, value)
            await db.commit()
    asyncio.run(apply())


def exists(session_id):
    async def check():
        async with session_factory() as db:
            return await db.get(TrainingSession, session_id) is not None
    return asyncio.run(check())


def test_history_hides_unstarted_attempt(client):
    headers = register(client)
    session_id = prepare(client, headers)

    assert client.get('/api/v1/training-sessions', headers=headers).json()['data'] == []
    assert client.get('/api/v1/training-sessions', headers=headers, params={'status': 'ACTIVE'}).json()['data'] == []
    assert session_id not in client.get('/api/v1/training-sessions/export', headers=headers).text

    mutate(session_id, current_round=1)
    items = client.get('/api/v1/training-sessions', headers=headers).json()['data']
    assert [row['id'] for row in items] == [session_id]


def test_cleanup_script_dry_run_then_deletes_only_empty_attempts(client):
    headers = register(client)
    stale_empty = prepare(client, headers)
    fresh_empty = prepare(client, headers)
    answered = prepare(client, headers)
    finished_empty = prepare(client, headers)
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    mutate(stale_empty, started_at=old)
    mutate(fresh_empty, started_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    mutate(answered, started_at=old, current_round=1)
    mutate(finished_empty, started_at=old, status='FINISHED', finished_at=old)

    async def add_user_message():
        async with session_factory() as db:
            db.add(Message(session_id=answered, round_no=1, speaker='USER', content='我先说结论。'))
            await db.commit()
    asyncio.run(add_user_message())

    dry = asyncio.run(cleanup_run(dry_run=True, minutes=30))
    assert dry['deleted'] == 0
    assert stale_empty in dry['ids']
    assert {fresh_empty, answered, finished_empty}.isdisjoint(dry['ids'])
    assert all(exists(session_id) for session_id in (stale_empty, fresh_empty, answered, finished_empty))

    real = asyncio.run(cleanup_run(dry_run=False, minutes=30))
    assert real['deleted'] == len(real['ids']) >= 1
    assert stale_empty in real['ids']
    assert not exists(stale_empty)
    assert all(exists(session_id) for session_id in (fresh_empty, answered, finished_empty))

    async def answered_intact():
        async with session_factory() as db:
            rows = (await db.scalars(select(Message).where(Message.session_id == answered))).all()
            return [row.content for row in rows]
    assert '我先说结论。' in asyncio.run(answered_intact())
