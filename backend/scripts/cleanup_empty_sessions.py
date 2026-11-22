"""清理"啥也没干"的空训练会话：0 轮、没有用户回答、没有评分、也没有消息的占位记录。

进面试房间时前端会先 POST /training-sessions/prepare 建一条占位会话（只带一句开场白）。
正常退出会 discard，异常退出（关标签页、断网、旧版本前端）就留在库里，训练记录页会把它当
"进行中 0/12 轮"列出来。本脚本兜底清理这些占位记录。

判定条件（全部满足才删）：
  status = ACTIVE、current_round = 0、无 Evaluation、无任何用户/对话消息
  （prepare 自动写入的 round_no=0 开场白不算用户数据）、创建超过 --minutes 分钟（默认 30）。

用法：
  python -m scripts.cleanup_empty_sessions --dry-run   # 只看会删哪些
  python -m scripts.cleanup_empty_sessions             # 真删
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import session_factory
from app.db.models import Evaluation, Message, ResumeContext, TrainingSession

DEFAULT_MINUTES = 30
SAMPLE_SIZE = 5


def cutoff_time(minutes: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


def aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def collect_targets(session: AsyncSession, cutoff: datetime) -> list[TrainingSession]:
    """空占位会话：0 轮、未开始、没有用户内容、也没有评分。"""
    answered = select(Message.session_id).where(Message.round_no > 0).union_all(
        select(Message.session_id).where(Message.speaker == "USER")
    )
    scored = select(Evaluation.session_id)
    rows = (
        await session.scalars(
            select(TrainingSession)
            .where(
                TrainingSession.status == "ACTIVE",
                TrainingSession.current_round == 0,
                TrainingSession.id.notin_(answered),
                TrainingSession.id.notin_(scored),
            )
            .order_by(TrainingSession.started_at)
        )
    ).all()
    return [item for item in rows if (aware(item.started_at) or cutoff) <= cutoff]


async def run(dry_run: bool, minutes: int) -> dict:
    cutoff = cutoff_time(minutes)
    async with session_factory() as session:
        targets = await collect_targets(session, cutoff)
        ids = [item.id for item in targets]
        print(f"cutoff={cutoff.isoformat()} minutes={minutes} matched={len(ids)}")
        for session_id in ids[:SAMPLE_SIZE]:
            print(f"  candidate: {session_id}")
        if dry_run:
            print("dry-run: nothing deleted")
            return {"matched": len(ids), "deleted": 0, "ids": ids}
        if ids:
            await session.execute(delete(Message).where(Message.session_id.in_(ids)))
            await session.execute(delete(ResumeContext).where(ResumeContext.session_id.in_(ids)))
            await session.execute(delete(TrainingSession).where(TrainingSession.id.in_(ids)))
            await session.commit()
        remaining = await session.scalar(
            select(func.count())
            .select_from(TrainingSession)
            .where(TrainingSession.status == "ACTIVE", TrainingSession.current_round == 0)
        )
        print(f"deleted={len(ids)} remaining_empty_active={int(remaining or 0)}")
        return {"matched": len(ids), "deleted": len(ids), "ids": ids, "remaining": int(remaining or 0)}


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description="清理 0 轮空占位训练会话")
    parser.add_argument("--dry-run", action="store_true", help="只列出会删哪些，不落库")
    parser.add_argument("--minutes", type=int, default=DEFAULT_MINUTES, help="只清理创建超过多少分钟的会话")
    args = parser.parse_args(argv)
    return asyncio.run(run(dry_run=args.dry_run, minutes=args.minutes))


if __name__ == "__main__":
    main()
