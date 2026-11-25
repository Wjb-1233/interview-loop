import asyncio
from datetime import datetime, timezone

from app.db.base import session_factory
from app.db.models import Message, TrainingSession
from tests.support.factories import client, register


def test_database_roundtrip_preserves_subsecond_interview_order(client):
    headers = register(client)
    user_id = client.get('/api/v1/auth/me', headers=headers).json()['data']['id']

    async def roundtrip():
        stamp = datetime(2026, 11, 24, 1, 0, 0, 123456, tzinfo=timezone.utc)
        async with session_factory() as db:
            training = TrainingSession(user_id=user_id, scene_id='scene-interview-03', started_at=stamp)
            db.add(training)
            await db.flush()
            message = Message(session_id=training.id, speaker='AI', round_no=0, content='请介绍项目。', created_at=stamp)
            db.add(message)
            await db.commit()
            sid, mid = training.id, message.id
        async with session_factory() as db:
            assert (await db.get(TrainingSession, sid)).started_at.microsecond == 123456
            assert (await db.get(Message, mid)).created_at.microsecond == 123456
    asyncio.run(roundtrip())
