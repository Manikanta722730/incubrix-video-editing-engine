"""FFmpeg discovery and media probe utilities."""

import os
import shutil
import subprocess
import json
from typing import Optional, Dict, Any, Tuple


def get_ffmpeg_path() -> str:
    """Finds FFmpeg executable: system PATH first, fallback to imageio_ffmpeg."""
    ffmpeg_env = os.getenv("FFMPEG_PATH")
    if ffmpeg_env and os.path.isfile(ffmpeg_env):
        return ffmpeg_env
    path_which = shutil.which("ffmpeg")
    if path_which:
        return path_which
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def get_ffprobe_path() -> str:
    """Finds FFprobe executable: system PATH or derived from ffmpeg directory."""
    ffprobe_env = os.getenv("FFPROBE_PATH")
    if ffprobe_env and os.path.isfile(ffprobe_env):
        return ffprobe_env
    path_which = shutil.which("ffprobe")
    if path_which:
        return path_which
    ffmpeg_path = get_ffmpeg_path()
    candidate = os.path.join(os.path.dirname(ffmpeg_path), "ffprobe.exe" if os.name == "nt" else "ffprobe")
    if os.path.isfile(candidate):
        return candidate
    return "ffprobe"


def probe_media_file(file_path: str) -> Dict[str, Any]:
    """Inspects a media file (MP4, MOV, WAV) returning duration, fps, resolution, audio."""
    duration_s = 0.0
    fps = 30.0
    width = 1920
    height = 1080
    has_audio = False

    # Try frame-accurate probe with OpenCV if available
    try:
        import cv2
        cap = cv2.VideoCapture(file_path)
        if cap.isOpened():
            c_fps = cap.get(cv2.CAP_PROP_FPS)
            c_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            c_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            c_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            if c_fps > 0 and c_count > 0:
                fps = c_fps
                duration_s = c_count / c_fps
                width = c_w
                height = c_h
    except Exception:
        pass

    ffmpeg = get_ffmpeg_path()
    cmd = [
        ffmpeg,
        "-i", file_path,
        "-hide_banner"
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    output = res.stderr

    # Fallback to FFmpeg duration if OpenCV didn't read it
    if duration_s <= 0.0:
        import re
        dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", output)
        if dur_match:
            h, m, s = dur_match.groups()
            duration_s = int(h) * 3600 + int(m) * 60 + float(s)

    # Check for Audio stream
    if "Audio:" in output:
        has_audio = True

    return {
        "duration_s": round(duration_s, 3),
        "fps": fps,
        "width": width,
        "height": height,
        "has_audio": has_audio,
        "raw_info": output[:500]
    }
