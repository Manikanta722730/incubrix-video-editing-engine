"""OpenTimelineIO export module.

Outstanding Level requirement:
Export: the timeline exports to OpenTimelineIO so other editors can open it.
"""

from __future__ import annotations
import os
from typing import Optional
import opentimelineio as otio
from engine.models import Timeline
from engine.timeline_core import TimelineCore


class OtioExporter:
    """Exports IncuBrix Timeline to OpenTimelineIO (.otio) format."""

    @staticmethod
    def export_timeline(timeline: Timeline, output_path: str, rate: float = 30.0) -> str:
        """Serializes timeline into a standard OpenTimelineIO (.otio) file."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        otio_timeline = otio.schema.Timeline(
            name=f"IncuBrix_Edit_{timeline.timeline_id[:8]}"
        )

        video_track = otio.schema.Track(
            name="Video Track",
            kind=otio.schema.TrackKind.Video
        )
        audio_track = otio.schema.Track(
            name="Audio Track",
            kind=otio.schema.TrackKind.Audio
        )

        source_media_url = timeline.source_media.storage_url or timeline.source_media.file_name

        for idx, clip in enumerate(timeline.video_track.clips):
            dur_orig = clip.source_end_s - clip.source_start_s
            start_frame = int(round(clip.source_start_s * rate))
            dur_frames = int(round(dur_orig * rate))

            source_range = otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(start_frame, rate),
                duration=otio.opentime.RationalTime(max(1, dur_frames), rate)
            )

            media_ref = otio.schema.ExternalReference(
                target_url=source_media_url,
                available_range=source_range
            )

            otio_clip = otio.schema.Clip(
                name=f"Clip_{idx+1}_{clip.clip_id[:6]}",
                media_reference=media_ref,
                source_range=source_range
            )

            if abs(clip.speed_factor - 1.0) > 0.01:
                # Add speed / time warp effect
                warp = otio.schema.LinearTimeWarp(
                    name=f"Speed_{clip.speed_factor}x",
                    time_scalar=clip.speed_factor
                )
                otio_clip.effects.append(warp)

            video_track.append(otio_clip)

            # Duplicate clip for audio track
            audio_clip = otio.schema.Clip(
                name=f"Audio_{idx+1}_{clip.clip_id[:6]}",
                media_reference=media_ref,
                source_range=source_range
            )
            audio_track.append(audio_clip)

        # Attach active captions as markers on timeline
        curr_offset_s = 0.0
        for cap in timeline.caption_track.captions:
            if cap.is_active:
                playout = TimelineCore.calculate_caption_playout(timeline, cap)
                if playout:
                    s_t, e_t = playout
                    mark_start = otio.opentime.RationalTime(int(round(s_t * rate)), rate)
                    mark_dur = otio.opentime.RationalTime(int(round((e_t - s_t) * rate)), rate)
                    marker = otio.schema.Marker(
                        name=f"Caption: {cap.text}",
                        marked_range=otio.opentime.TimeRange(mark_start, mark_dur),
                        color=otio.schema.MarkerColor.RED if cap.style.color == "red" else otio.schema.MarkerColor.WHITE
                    )
                    otio_timeline.tracks.markers.append(marker)

        otio_timeline.tracks.append(video_track)
        otio_timeline.tracks.append(audio_track)

        otio.adapters.write_to_file(otio_timeline, output_path)
        return output_path

