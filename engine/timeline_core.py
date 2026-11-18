"""Core deterministic timeline manipulation engine.

Content-addressed operations:
- Clips represent intervals of the untouched original media.
- Captions and audio effects anchor to WordToken IDs.
- Playout timestamps are derived purely from active clips.
"""

from __future__ import annotations
import copy
from typing import List, Dict, Optional, Tuple, Set
from engine.models import (
    Timeline,
    TimelineClip,
    ContentCaption,
    WordToken,
    BleepInterval,
    TimePolicy
)


class TimelineCore:
    """Deterministic timeline engine manipulating clips, words, and content anchors."""

    @staticmethod
    def get_active_word_ids(timeline: Timeline) -> Set[str]:
        """Returns the set of word IDs present across all currently active clips."""
        active_ids = set()
        for clip in timeline.video_track.clips:
            active_ids.update(clip.word_ids)
        return active_ids

    @staticmethod
    def calculate_caption_playout(
        timeline: Timeline,
        caption: ContentCaption
    ) -> Optional[Tuple[float, float]]:
        """Calculates current timeline playout (start_timeline_s, end_timeline_s) for a caption.

        Respects speed factors and ensures minimum readable duration (0.70s).
        Returns None if caption is inactive or anchored words are missing.
        """
        if not caption.is_active or not caption.anchor_word_ids:
            return None

        words_by_id = {w.id: w for w in timeline.transcript.words}
        active_anchor_words = [words_by_id[wid] for wid in caption.anchor_word_ids if wid in words_by_id]
        if not active_anchor_words:
            return None

        anchor_min_orig = min(w.start_s for w in active_anchor_words)
        anchor_max_orig = max(w.end_s for w in active_anchor_words)

        # Locate where anchor_min_orig and anchor_max_orig land on the active timeline
        curr_offset = 0.0
        start_timeline = None
        end_timeline = None

        for clip in timeline.video_track.clips:
            clip_dur = clip.duration_s
            # Does anchor start fall in this clip?
            if start_timeline is None and (clip.source_start_s <= anchor_min_orig <= clip.source_end_s):
                dt = (anchor_min_orig - clip.source_start_s) / clip.speed_factor
                start_timeline = curr_offset + dt

            # Does anchor end fall in this clip?
            if clip.source_start_s <= anchor_max_orig <= clip.source_end_s:
                dt = (anchor_max_orig - clip.source_start_s) / clip.speed_factor
                end_timeline = curr_offset + dt

            curr_offset += clip_dur

        if start_timeline is None or end_timeline is None:
            return None

        # Readable minimum duration rule (Advanced level: ~0.70s minimum)
        dur = end_timeline - start_timeline
        if dur < caption.min_duration_s:
            end_timeline = start_timeline + caption.min_duration_s

        return round(start_timeline, 3), round(end_timeline, 3)

    @staticmethod
    def refresh_caption_statuses(timeline: Timeline) -> List[str]:
        """Evaluates all captions against active clips.

        Rule:
        - If 100% of anchor words remain: active.
        - If >= 50% remain: active (spanning remaining words).
        - If < 50% remain: deactivated and user is informed.
        """
        notifications = []
        active_words = TimelineCore.get_active_word_ids(timeline)

        for cap in timeline.caption_track.captions:
            if not cap.anchor_word_ids:
                continue
            total_anchors = len(cap.anchor_word_ids)
            surviving = sum(1 for wid in cap.anchor_word_ids if wid in active_words)
            ratio = surviving / total_anchors if total_anchors > 0 else 0.0

            if ratio == 0.0:
                if cap.is_active:
                    cap.is_active = False
                    notifications.append(f"Caption '{cap.text}' hidden (all anchored words cut)")
            elif ratio < 0.50:
                if cap.is_active:
                    cap.is_active = False
                    notifications.append(f"Caption '{cap.text}' hidden (less than 50% of phrase remains)")
            else:
                if not cap.is_active:
                    cap.is_active = True
                    notifications.append(f"Caption '{cap.text}' restored onto its anchor words")

        return notifications

    @staticmethod
    def slice_clips_for_cut(
        clips: List[TimelineClip],
        words: List[WordToken],
        cut_start_orig: float,
        cut_end_orig: float
    ) -> List[TimelineClip]:
        """Deterministic clip slicing for cut ranges."""
        new_clips: List[TimelineClip] = []

        for clip in clips:
            c_start = clip.source_start_s
            c_end = clip.source_end_s

            # Case 1: Clip completely outside cut range
            if c_end <= cut_start_orig or c_start >= cut_end_orig:
                new_clips.append(clip)
                continue

            # Case 2: Clip completely inside cut range
            if cut_start_orig <= c_start and c_end <= cut_end_orig:
                continue  # Completely deleted

            # Case 3: Cut lands strictly inside clip (splits into two)
            if c_start < cut_start_orig and cut_end_orig < c_end:
                # Left clip
                left_words = [
                    w.id for w in words
                    if w.id in clip.word_ids and w.start_s >= c_start and w.end_s <= cut_start_orig
                ]
                new_clips.append(
                    TimelineClip(
                        source_start_s=c_start,
                        source_end_s=cut_start_orig,
                        speed_factor=clip.speed_factor,
                        word_ids=left_words,
                        is_muted=clip.is_muted
                    )
                )
                # Right clip
                right_words = [
                    w.id for w in words
                    if w.id in clip.word_ids and w.start_s >= cut_end_orig and w.end_s <= c_end
                ]
                new_clips.append(
                    TimelineClip(
                        source_start_s=cut_end_orig,
                        source_end_s=c_end,
                        speed_factor=clip.speed_factor,
                        word_ids=right_words,
                        is_muted=clip.is_muted
                    )
                )
                continue

            # Case 4: Overlaps clip start
            if cut_start_orig <= c_start < cut_end_orig < c_end:
                surviving_words = [
                    w.id for w in words
                    if w.id in clip.word_ids and w.start_s >= cut_end_orig and w.end_s <= c_end
                ]
                new_clips.append(
                    TimelineClip(
                        source_start_s=cut_end_orig,
                        source_end_s=c_end,
                        speed_factor=clip.speed_factor,
                        word_ids=surviving_words,
                        is_muted=clip.is_muted
                    )
                )
                continue

            # Case 5: Overlaps clip end
            if c_start < cut_start_orig < c_end <= cut_end_orig:
                surviving_words = [
                    w.id for w in words
                    if w.id in clip.word_ids and w.start_s >= c_start and w.end_s <= cut_start_orig
                ]
                new_clips.append(
                    TimelineClip(
                        source_start_s=c_start,
                        source_end_s=cut_start_orig,
                        speed_factor=clip.speed_factor,
                        word_ids=surviving_words,
                        is_muted=clip.is_muted
                    )
                )

        return new_clips

    @staticmethod
    def slice_clips_for_speed(
        clips: List[TimelineClip],
        words: List[WordToken],
        speed_start_orig: float,
        speed_end_orig: float,
        speed_factor: float
    ) -> List[TimelineClip]:
        """Applies speed factor to specified range.

        If target range overlaps existing clips with different speed factors,
        the new speed factor replaces the range deterministically.
        """
        new_clips: List[TimelineClip] = []

        for clip in clips:
            c_start = clip.source_start_s
            c_end = clip.source_end_s

            # Outside range
            if c_end <= speed_start_orig or c_start >= speed_end_orig:
                new_clips.append(clip)
                continue

            # Completely inside
            if speed_start_orig <= c_start and c_end <= speed_end_orig:
                clip_copy = clip.model_copy()
                clip_copy.speed_factor = speed_factor
                new_clips.append(clip_copy)
                continue

            # Splits into 3 (before, inside, after)
            if c_start < speed_start_orig and speed_end_orig < c_end:
                w_left = [w.id for w in words if w.id in clip.word_ids and w.end_s <= speed_start_orig]
                w_mid = [w.id for w in words if w.id in clip.word_ids and speed_start_orig <= w.start_s and w.end_s <= speed_end_orig]
                w_right = [w.id for w in words if w.id in clip.word_ids and w.start_s >= speed_end_orig]

                new_clips.append(TimelineClip(source_start_s=c_start, source_end_s=speed_start_orig, speed_factor=clip.speed_factor, word_ids=w_left))
                new_clips.append(TimelineClip(source_start_s=speed_start_orig, source_end_s=speed_end_orig, speed_factor=speed_factor, word_ids=w_mid))
                new_clips.append(TimelineClip(source_start_s=speed_end_orig, source_end_s=c_end, speed_factor=clip.speed_factor, word_ids=w_right))
                continue

            # Overlaps start
            if speed_start_orig <= c_start < speed_end_orig < c_end:
                w_mid = [w.id for w in words if w.id in clip.word_ids and w.end_s <= speed_end_orig]
                w_right = [w.id for w in words if w.id in clip.word_ids and w.start_s >= speed_end_orig]
                new_clips.append(TimelineClip(source_start_s=c_start, source_end_s=speed_end_orig, speed_factor=speed_factor, word_ids=w_mid))
                new_clips.append(TimelineClip(source_start_s=speed_end_orig, source_end_s=c_end, speed_factor=clip.speed_factor, word_ids=w_right))
                continue

            # Overlaps end
            if c_start < speed_start_orig < c_end <= speed_end_orig:
                w_left = [w.id for w in words if w.id in clip.word_ids and w.end_s <= speed_start_orig]
                w_mid = [w.id for w in words if w.id in clip.word_ids and w.start_s >= speed_start_orig]
                new_clips.append(TimelineClip(source_start_s=c_start, source_end_s=speed_start_orig, speed_factor=clip.speed_factor, word_ids=w_left))
                new_clips.append(TimelineClip(source_start_s=speed_start_orig, source_end_s=c_end, speed_factor=speed_factor, word_ids=w_mid))

        return new_clips

