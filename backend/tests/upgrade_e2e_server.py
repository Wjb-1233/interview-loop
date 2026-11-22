"""Explicitly invoked offline browser-test server; never imported by the app."""
import os
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

database = Path(tempfile.gettempdir()) / f"yanjie-upgrade-e2e-{uuid4().hex}.db"
os.environ.update(ENVIRONMENT="test", DATABASE_URL=f"sqlite+aiosqlite:///{database.as_posix()}", AUTO_CREATE_SCHEMA="true", REDIS_ENABLED="false", LLM_API_KEY="", REQUIRE_EMAIL_VERIFICATION="false", DOUBAO_REALTIME_APP_ID="", DOUBAO_REALTIME_ACCESS_TOKEN="", JWT_SECRET="offline-browser-test-secret-over-32-characters", CORS_ORIGINS="http://127.0.0.1:5175")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.support.factories import model_response
from app.infrastructure.llm import llm_gateway
from app.main import app


async def stream(*args, **kwargs):
    yield "你如何验证自己的方案和结果？"


if __name__ == "__main__":
    import uvicorn
    type(llm_gateway).configured = property(lambda self: True)
    llm_gateway.complete_json = model_response
    llm_gateway.stream_text = stream
    try:
        uvicorn.run(app, host="127.0.0.1", port=8081, log_level="warning")
    finally:
        database.unlink(missing_ok=True)
