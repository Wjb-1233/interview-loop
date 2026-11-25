"""Make the complete test suite independent from developer and production data."""

from __future__ import annotations

import asyncio
import os
import tempfile
import shutil
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url


TEST_DATABASE = Path(tempfile.gettempdir()) / f"career-coach-pytest-{uuid4().hex}.db"
MYSQL_TEST_URL = os.environ.get("CAREER_TEST_DATABASE_URL", "")
if MYSQL_TEST_URL:
    url = make_url(MYSQL_TEST_URL)
    if (url.drivername != "mysql+asyncmy" or url.host not in {"localhost", "127.0.0.1"}
            or not (url.database or "").startswith("career_coach_test_")
            or not (url.username or "").startswith("cc_test_")):
        raise RuntimeError("MySQL tests require a local disposable career_coach_test_ schema and cc_test_ user")
TEST_MEDIA = Path(tempfile.mkdtemp(prefix="career-coach-pytest-media-"))

# conftest is loaded before test modules, so application settings are created only
# after these deterministic, offline test values are installed.
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": MYSQL_TEST_URL or f"sqlite+aiosqlite:///{TEST_DATABASE.as_posix()}",
        "AUTO_CREATE_SCHEMA": "true",
        "REDIS_ENABLED": "true" if os.environ.get("CAREER_TEST_REDIS_URL") else "false",
        "REDIS_URL": os.environ.get("CAREER_TEST_REDIS_URL", "redis://127.0.0.1:6380/15"),
        "RECORDING_DIR": str(TEST_MEDIA / "recordings"),
        "LESSON_VIDEO_DIR": str(TEST_MEDIA / "lessons"),
        "TTS_DIR": str(TEST_MEDIA / "tts"),
        "DB_POOL_SIZE": "1",
        "LLM_API_KEY": "",
        "JWT_SECRET": "isolated-test-secret-longer-than-32-characters",
        "CORS_ORIGINS": "http://testserver",
    }
)

if MYSQL_TEST_URL:
    # TestClient and asyncio.run use separate loops. Disable connection reuse in
    # this test process only; the actual API server retains its production pool.
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool
    from app.db import base

    asyncio.run(base.engine.dispose())
    base.engine = create_async_engine(MYSQL_TEST_URL, poolclass=NullPool)
    base.session_factory.configure(bind=base.engine)
    async def reset_mysql_test_schema():
        name = base.engine.url.database
        assert name and name.startswith("career_coach_test_") and name.replace("_", "").isalnum()
        async with base.engine.begin() as connection:
            await connection.exec_driver_sql(f"DROP DATABASE IF EXISTS `{name}`")
            await connection.exec_driver_sql(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    asyncio.run(reset_mysql_test_schema())


@pytest.fixture(scope="session", autouse=True)
def isolated_test_database() -> Iterator[Path]:
    """Remove the temporary database after all app lifespans have completed."""

    yield TEST_DATABASE

    from app.db.base import engine

    asyncio.run(engine.dispose())
    for suffix in ("", "-journal", "-shm", "-wal"):
        Path(f"{TEST_DATABASE}{suffix}").unlink(missing_ok=True)
    assert TEST_MEDIA.resolve().parent == Path(tempfile.gettempdir()).resolve()
    assert TEST_MEDIA.name.startswith("career-coach-pytest-media-")
    shutil.rmtree(TEST_MEDIA)
