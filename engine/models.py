"""Data models for the IncuBrix Prompt-Based Video Editing Engine.

All edits are content-anchored: attached to WordToken instances rather than clock times.
"""

from __future__ import annotations
import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ResponseStatus(str, Enum):
    APPLIED = "applied"
    NEEDS_CLARIFICATION = "needs_clarification"
    REJECTED = "rejected"


class TimePolicy(str, Enum):
    ORIGINAL_MEDIA_TIME = "original_media_time"
    CURRENT_TIMELINE_TIME = "current_timeline_time"


class WordToken(BaseModel):
    id: str = Field(default_factory=lambda: f"w_{uuid.uuid4().hex[:8]}")
    text: str
    start_s: float
    end_s: float
    speaker: str = "speaker_1"
    confidence: float = 1.0
    is_filler: bool = False
    low_confidence: bool = False

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)


class TimelineClip(BaseModel):
    clip_id: str = Field(default_factory=lambda: f"clip_{uuid.uuid4().hex[:8]}")
    source_start_s: float
    source_end_s: float
    speed_factor: float = 1.0
    word_ids: List[str] = Field(default_factory=list)
    is_muted: bool = False

    @property
    def duration_s(self) -> float:
        raw_dur = max(0.0, self.source_end_s - self.source_start_s)
        return raw_dur / self.speed_factor if self.speed_factor > 0 else raw_dur


class CaptionStyle(BaseModel):
    color: str = "white"
    font_size: int = 24
    position: str = "bottom"  # top, center, bottom


class ContentCaption(BaseModel):
    id: str = Field(default_factory=lambda: f"cap_{uuid.uuid4().hex[:8]}")
    text: str
    anchor_word_ids: List[str] = Field(default_factory=list)
    is_active: bool = True
    style: CaptionStyle = Field(default_factory=CaptionStyle)
    min_duration_s: float = 0.70  # Advanced level: sped-up captions keep a readable minimum (~0.7s)


class BleepInterval(BaseModel):
    word_id: str
    frequency_hz: int = 1000


class BackgroundMusic(BaseModel):
    music_url: str
    volume: float = 0.20
    duck_db: float = -18.0


class AudioTrack(BaseModel):
    ducking_enabled: bool = False
    ducking_db: float = -18.0
    background_music: Optional[BackgroundMusic] = None
    bleeps: List[BleepInterval] = Field(default_factory=list)


class VideoTrack(BaseModel):
    clips: List[TimelineClip] = Field(default_factory=list)


class CaptionTrack(BaseModel):
    captions: List[ContentCaption] = Field(default_factory=list)


class HistoryStep(BaseModel):
    step_id: str = Field(default_factory=lambda: f"step_{uuid.uuid4().hex[:8]}")
    op_type: str
    instruction_text: str
    params: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    # Stored state snapshot for absolute determinism in rollback
    snapshot_data: Optional[Dict[str, Any]] = None
    post_snapshot: Optional[Dict[str, Any]] = None


class SourceMedia(BaseModel):
    source_id: str
    file_name: str
    duration_s: float
    fps: float = 30.0
    width: int = 1920
    height: int = 1080
    has_audio: bool = True
    source_sha256: str
    storage_url: Optional[str] = None


class Transcript(BaseModel):
    words: List[WordToken] = Field(default_factory=list)
    speakers: List[str] = Field(default_factory=lambda: ["speaker_1"])
    language: str = "en"


class DerivedTiming(BaseModel):
    total_duration_s: float = 0.0
    active_clip_count: int = 0
    timeline_hash: str = ""


class Timeline(BaseModel):
    version: str = "1.0.0"
    timeline_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_media: SourceMedia
    transcript: Transcript
    video_track: VideoTrack = Field(default_factory=VideoTrack)
    audio_track: AudioTrack = Field(default_factory=AudioTrack)
    caption_track: CaptionTrack = Field(default_factory=CaptionTrack)
    history_steps: List[HistoryStep] = Field(default_factory=list)
    undo_pointer: int = -1  # Points to current active index in history_steps
    derived_timing: DerivedTiming = Field(default_factory=DerivedTiming)

    def compute_duration(self) -> float:
        return sum(clip.duration_s for clip in self.video_track.clips)

    def compute_canonical_hash(self) -> str:
        """Computes a deterministic SHA256 hash of the complete timeline state.

        Any identical state produces the exact same hash.
        """
        canonical_dict = {
            "version": self.version,
            "source_sha256": self.source_media.source_sha256,
            "clips": [
                {
                    "source_start": round(c.source_start_s, 4),
                    "source_end": round(c.source_end_s, 4),
                    "speed": round(c.speed_factor, 4),
                    "words": c.word_ids,
                    "muted": c.is_muted,
                }
                for c in self.video_track.clips
            ],
            "captions": [
                {
                    "text": c.text,
                    "anchors": c.anchor_word_ids,
                    "active": c.is_active,
                    "color": c.style.color,
                    "pos": c.style.position,
                }
                for c in sorted(self.caption_track.captions, key=lambda x: (x.text, "".join(x.anchor_word_ids)))
            ],
            "audio": {
                "ducking": self.audio_track.ducking_enabled,
                "has_music": self.audio_track.background_music is not None,
                "bleeps": [b.word_id for b in self.audio_track.bleeps],
            },
        }
        encoded = json.dumps(canonical_dict, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def update_derived_timing(self) -> None:
        self.derived_timing.total_duration_s = round(self.compute_duration(), 4)
        self.derived_timing.active_clip_count = len(self.video_track.clips)
        self.derived_timing.timeline_hash = self.compute_canonical_hash()


class EngineResponse(BaseModel):
    status: ResponseStatus
    operations: List[str] = Field(default_factory=list)
    summary: str = ""
    question: Optional[str] = None
    options: Optional[List[str]] = None
    reason: Optional[str] = None
    timeline_hash: str = ""
    duration_s: float = 0.0
    time_policy: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
