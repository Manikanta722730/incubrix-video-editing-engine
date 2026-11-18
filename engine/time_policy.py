"""Time policy implementation and natural language time parsing.

Must-have 7:
When a user says "at 1:20" after earlier cuts, the system uses one stated policy
(original_media_time or current_timeline_time), everywhere, and states which one in its answer.
"""

from __future__ import annotations
import re
from typing import Optional, Tuple, List
from engine.models import Timeline, TimePolicy


def parse_time_expression(expr: str, total_duration: float = 0.0) -> Optional[float]:
    """Parses various natural and numeric time expressions into seconds."""
    expr = expr.strip().lower()

    if expr in ["end", "video_end", "total_duration"]:
        return total_duration

    # Match "the last X seconds"
    m_last = re.match(r"(?:the\s+)?last\s+(\d+(?:\.\d+)?)\s*(?:s|sec|seconds?)?", expr)
    if m_last:
        sec = float(m_last.group(1))
        return max(0.0, total_duration - sec)

    # Match "the first X seconds"
    m_first = re.match(r"(?:the\s+)?first\s+(\d+(?:\.\d+)?)\s*(?:s|sec|seconds?)?", expr)
    if m_first:
        return float(m_first.group(1))

    # Match HH:MM:SS or MM:SS or M:SS (with optional decimal seconds)
    m_clock = re.match(r"^(\d+):([0-5]?\d(?:\.\d+)?)(?::([0-5]?\d(?:\.\d+)?))?$", expr)
    if m_clock:
        parts = [p for p in m_clock.groups() if p is not None]
        if len(parts) == 2:
            minutes, seconds = float(parts[0]), float(parts[1])
            return minutes * 60.0 + seconds
        elif len(parts) == 3:
            hours, minutes, seconds = float(parts[0]), float(parts[1]), float(parts[2])
            return hours * 3600.0 + minutes * 60.0 + seconds

    # Match "80 seconds", "45s", "120 sec"
    m_sec = re.match(r"^(\d+(?:\.\d+)?)\s*(?:s|sec|seconds?)$", expr)
    if m_sec:
        return float(m_sec.group(1))

    # Match "a minute twenty", "one minute twenty", "two minutes 15 seconds"
    m_nat = re.match(
        r"^(?:a|one|two|three|four|five|\d+)\s+minutes?(?:\s+(?:and\s+)?(\d+|twenty|thirty|forty|fifty))?(?:\s*seconds?)?$",
        expr
    )
    if m_nat:
        # Word numbers map
        word_num = {
            "a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50
        }
        parts = expr.split()
        mins = word_num.get(parts[0], int(parts[0]) if parts[0].isdigit() else 1)
        secs = 0.0
        for p in parts[2:]:
            if p in word_num:
                secs += word_num[p]
            elif p.isdigit():
                secs += float(p)
        return mins * 60.0 + secs

    # Raw float/int string
    try:
        return float(expr)
    except ValueError:
        return None


def format_timestamp(seconds: float) -> str:
    """Formats seconds into MM:SS.mmm format."""
    total_ms = int(round(seconds * 1000))
    m = (total_ms // 60000)
    s = (total_ms % 60000) // 1000
    ms = total_ms % 1000
    if ms > 0:
        return f"{m:02d}:{s:02d}.{ms:03d}"
    return f"{m:02d}:{s:02d}"


class TimePolicyResolver:
    """Resolves and translates time ranges between original media time and current timeline time."""

    def __init__(self, default_policy: TimePolicy = TimePolicy.ORIGINAL_MEDIA_TIME):
        self.default_policy = default_policy

    def resolve_range(
        self,
        timeline: Timeline,
        start_val: float,
        end_val: float,
        specified_policy: Optional[TimePolicy] = None
    ) -> Tuple[float, float, str]:
        """Returns (original_start_s, original_end_s, policy_explanation)."""
        policy = specified_policy or self.default_policy

        if policy == TimePolicy.ORIGINAL_MEDIA_TIME:
            orig_start = start_val
            orig_end = end_val
            # Compute where this currently falls on active timeline for user clarity
            curr_start = self.original_to_current(timeline, orig_start)
            curr_end = self.original_to_current(timeline, orig_end)

            curr_str = f"{format_timestamp(curr_start or 0.0)} to {format_timestamp(curr_end or 0.0)}"
            explanation = (
                f"Using policy '{policy.value}': input {format_timestamp(start_val)}-{format_timestamp(end_val)} "
                f"maps to current timeline {curr_str}."
            )
            return orig_start, orig_end, explanation
        else:
            # Policy is current_timeline_time
            orig_start = self.current_to_original(timeline, start_val)
            orig_end = self.current_to_original(timeline, end_val)
            explanation = (
                f"Using policy '{policy.value}': timeline position {format_timestamp(start_val)}-{format_timestamp(end_val)} "
                f"maps to original media {format_timestamp(orig_start)}-{format_timestamp(orig_end)}."
            )
            return orig_start, orig_end, explanation

    def original_to_current(self, timeline: Timeline, orig_time: float) -> Optional[float]:
        """Translates an original media timestamp to its current playout position on the timeline.

        Returns None if that timestamp was cut.
        """
        curr_offset = 0.0
        for clip in timeline.video_track.clips:
            if clip.source_start_s <= orig_time <= clip.source_end_s:
                delta_orig = orig_time - clip.source_start_s
                delta_timeline = delta_orig / clip.speed_factor
                return curr_offset + delta_timeline
            curr_offset += clip.duration_s
        return None

    def current_to_original(self, timeline: Timeline, curr_time: float) -> float:
        """Translates a current playout position on the timeline to the original media timestamp."""
        elapsed = 0.0
        for clip in timeline.video_track.clips:
            if elapsed + clip.duration_s >= curr_time:
                delta = curr_time - elapsed
                orig_delta = delta * clip.speed_factor
                return clip.source_start_s + orig_delta
            elapsed += clip.duration_s
        # If beyond end, clamp to end of last clip or total source duration
        if timeline.video_track.clips:
            return timeline.video_track.clips[-1].source_end_s
        return timeline.source_media.duration_s
