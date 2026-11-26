import shutil
from pathlib import Path


def ffmpeg_binary() -> str:
    project_root = Path(__file__).resolve().parents[3]
    bundled = project_root / "tools" / "ffmpeg" / "node_modules" / "ffmpeg-static" / "ffmpeg.exe"
    if bundled.is_file():
        return str(bundled)
    found = shutil.which("ffmpeg")
    if not found:
        raise RuntimeError("找不到 ffmpeg")
    return found
