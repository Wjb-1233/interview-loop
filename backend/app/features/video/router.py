"""Compatibility tombstone for the retired recording-upload workflow."""
from fastapi import APIRouter
from app.core.errors import AppError
from app.core.security import CurrentUser

router = APIRouter(prefix="/video-interviews", tags=["已停用接口"])

@router.post("")
async def retired_video_upload(user: CurrentUser):
    raise AppError(410, "VIDEO_UPLOAD_RETIRED", "录像上传分析已停用，请使用实时视频面试；已有录像与报告仍可查看")
