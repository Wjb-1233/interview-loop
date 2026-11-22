from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import ok
from app.core.security import CurrentUser
from app.db.base import get_session
from app.features.evaluations.comparison_view import build_comparison
from app.features.evaluations.service import evaluate_session, get_evaluation

router = APIRouter(prefix="/evaluations", tags=["智能评分"])
DbSession = Annotated[AsyncSession, Depends(get_session)]


@router.post("/{session_id}", status_code=201)
async def evaluate(
    session_id: str, user: CurrentUser, session: DbSession, force: bool = False
) -> dict:
    """生成评分；force=true 可修复降级、待重评及证据不足的报告。"""
    result = await evaluate_session(session, user.id, session_id, force=force)
    return ok(result.model_dump(by_alias=True))


@router.get("/{session_id}")
async def get_one(session_id: str, user: CurrentUser, session: DbSession) -> dict:
    result = await get_evaluation(session, user.id, session_id)
    return ok(result.model_dump(by_alias=True))


@router.get("/{session_id}/comparison")
async def compare_with_previous(session_id: str, user: CurrentUser, session: DbSession) -> dict:
    """两次训练的对比：同场景比四维与逐轮，不同场景只比通用指标。"""
    return ok(await build_comparison(session, user.id, session_id))

