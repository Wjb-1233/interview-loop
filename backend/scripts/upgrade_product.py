"""Back up affected records before applying the product cleanup migration.

Run from backend: .venv\Scripts\python.exe -m scripts.upgrade_product
"""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.db.base import engine


async def backup() -> Path:
    root = Path(__file__).resolve().parents[2]
    directory = root / "backups"
    directory.mkdir(exist_ok=True)
    payload = {}
    async with engine.connect() as connection:
        names = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
        for table in ("alembic_version", "scripts", "training_plans", "training_sessions", "analysis_tasks", "stories", "resume_diagnoses", "group_interviews", "coding_submissions"):
            if table in names:
                result = await connection.execute(text(f"SELECT * FROM {table}"))
                payload[table] = [dict(row) for row in result.mappings()]
    await engine.dispose()
    target = directory / f"product-upgrade-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
    return target


if __name__ == "__main__":
    target = asyncio.run(backup())
    print(f"Affected records backed up: {target}")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    print("Database migration completed.")
