from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import ok
from app.core.security import CurrentUser
from app.db.base import get_session
from app.features.dashboard.service import dashboard_data

router = APIRouter(prefix="/dashboard", tags=["成长看板"])
DbSession = Annotated[AsyncSession, Depends(get_session)]


@router.get("")
async def dashboard(
    user: CurrentUser,
    session: DbSession,
    channel: Literal["TEXT", "VOICE", "VIDEO"] | None = None,
    scene_id: str | None = None,
    anchor_session_id: str | None = None,
) -> dict:
    return ok(await dashboard_data(session, user.id, channel, scene_id, anchor_session_id))
