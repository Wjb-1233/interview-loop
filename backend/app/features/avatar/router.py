"""面试官数字人视频：只下发短时令牌，API Key 永远不下发到浏览器。"""

from fastapi import APIRouter

from app.core.responses import ok
from app.core.security import CurrentUser
from app.features.avatar import service

router = APIRouter(prefix="/avatar", tags=["数字人"])


@router.get("/simli-session")
async def simli_session(user: CurrentUser) -> dict:
    """返回 5 分钟有效的 Simli 会话令牌；未配置 503、上游失败 502，前端两种情况都回退本地形象。"""

    return ok(await service.create_session_token())
