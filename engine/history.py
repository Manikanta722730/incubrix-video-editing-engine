"""History management, Undo/Redo stack, and selective edit restoration.

Must-haves 1 & 6:
- Never damage original; every edit is an immutable step in history.
- One instruction = one undo.
- Applying a new edit clears the redo stack.
- Supports selective restoration of specific earlier edits.
"""

from __future__ import annotations
import copy
from typing import Optional, Dict, Any, Tuple, List
from engine.models import Timeline, HistoryStep, TimelineClip, ContentCaption, AudioTrack, VideoTrack, CaptionTrack


class HistoryManager:
    """Manages immutable snapshots and reversible timeline edits."""

    @staticmethod
    def capture_snapshot(timeline: Timeline) -> Dict[str, Any]:
        """Creates an exact snapshot of editable tracks and derived values."""
        return {
            "video_track": [c.model_dump() for c in timeline.video_track.clips],
            "audio_track": timeline.audio_track.model_dump(),
            "caption_track": [cap.model_dump() for cap in timeline.caption_track.captions],
        }

    @staticmethod
    def apply_snapshot(timeline: Timeline, snapshot: Dict[str, Any]) -> None:
        """Restores editable tracks from a snapshot."""
        timeline.video_track = VideoTrack(
            clips=[TimelineClip(**c) for c in snapshot["video_track"]]
        )
        timeline.audio_track = AudioTrack(**snapshot["audio_track"])
        timeline.caption_track = CaptionTrack(
            captions=[ContentCaption(**cap) for cap in snapshot["caption_track"]]
        )
        timeline.update_derived_timing()

    @staticmethod
    def push_step(
        timeline: Timeline,
        op_type: str,
        instruction_text: str,
        params: Dict[str, Any],
        pre_snapshot: Dict[str, Any]
    ) -> HistoryStep:
        """Adds a new history step and clears any redo states."""
        # Truncate forward redo history if we performed edits after an undo
        if timeline.undo_pointer < len(timeline.history_steps) - 1:
            timeline.history_steps = timeline.history_steps[:timeline.undo_pointer + 1]

        post_snap = HistoryManager.capture_snapshot(timeline)
        step = HistoryStep(
            op_type=op_type,
            instruction_text=instruction_text,
            params=params,
            snapshot_data=pre_snapshot,
            post_snapshot=post_snap
        )
        timeline.history_steps.append(step)
        timeline.undo_pointer = len(timeline.history_steps) - 1
        return step

    @staticmethod
    def undo(timeline: Timeline) -> Tuple[bool, str]:
        """Reverses exactly one instruction."""
        if timeline.undo_pointer < 0:
            return False, "Nothing to undo: history is at the beginning"

        step_to_revert = timeline.history_steps[timeline.undo_pointer]
        if step_to_revert.snapshot_data is None:
            return False, "Cannot undo step: missing snapshot"

        HistoryManager.apply_snapshot(timeline, step_to_revert.snapshot_data)
        timeline.undo_pointer -= 1
        return True, f"Reversed step: '{step_to_revert.instruction_text}' ({step_to_revert.op_type})"

    @staticmethod
    def redo(timeline: Timeline) -> Tuple[bool, str]:
        """Re-applies a previously undone instruction."""
        if timeline.undo_pointer >= len(timeline.history_steps) - 1:
            return False, "Nothing to redo: history is at the latest step"

        next_index = timeline.undo_pointer + 1
        step_to_redo = timeline.history_steps[next_index]
        if step_to_redo.post_snapshot is not None:
            HistoryManager.apply_snapshot(timeline, step_to_redo.post_snapshot)
        timeline.undo_pointer = next_index
        return True, f"Redid step: '{step_to_redo.instruction_text}'"

    @staticmethod
    def restore_specific_edit(timeline: Timeline, target: str) -> Tuple[bool, str, Dict[str, Any]]:
        """Restores a specific earlier edit without discarding subsequent non-conflicting edits.

        E.g., "put the intro back", "undo the second-to-last cut but keep the music".
        """
        lower = target.lower()

        # Find candidate cut operations in history
        cut_steps = [
            (idx, s) for idx, s in enumerate(timeline.history_steps)
            if s.op_type in ["cut_range", "cut_topic"] and idx <= timeline.undo_pointer
        ]

        if not cut_steps:
            return False, f"No previous cut operations found to restore for '{target}'", {}

        target_step_idx = None
        target_step = None

        if "intro" in lower or "first" in lower:
            # First cut
            target_step_idx, target_step = cut_steps[0]
        elif "second-to-last" in lower or "second to last" in lower:
            if len(cut_steps) >= 2:
                target_step_idx, target_step = cut_steps[-2]
            else:
                target_step_idx, target_step = cut_steps[0]
        elif "last" in lower or "what i removed" in lower:
            target_step_idx, target_step = cut_steps[-1]
        else:
            # Default to first cut matching
            target_step_idx, target_step = cut_steps[0]

        # Retrieve the cut range from params
        start_s = target_step.params.get("start_s", 0.0)
        end_s = target_step.params.get("end_s", 30.0)

        # Re-insert the restored clip into video_track
        # Check all words belonging to this range
        words_in_range = [
            w.id for w in timeline.transcript.words
            if w.start_s >= start_s and w.end_s <= end_s
        ]

        restored_clip = TimelineClip(
            source_start_s=start_s,
            source_end_s=end_s,
            speed_factor=1.0,
            word_ids=words_in_range
        )

        # Insert at correct sequential position based on source_start_s
        inserted = False
        new_clips = []
        for c in timeline.video_track.clips:
            if not inserted and c.source_start_s >= end_s:
                new_clips.append(restored_clip)
                inserted = True
            new_clips.append(c)
        if not inserted:
            new_clips.append(restored_clip)

        timeline.video_track.clips = new_clips
        timeline.update_derived_timing()

        # Check caption reactivations
        from engine.timeline_core import TimelineCore
        reactivations = TimelineCore.refresh_caption_statuses(timeline)

        desc = f"Restored range {start_s:.1f}s-{end_s:.1f}s from edit '{target_step.instruction_text}'."
        if reactivations:
            desc += " " + "; ".join(reactivations) + "."

        return True, desc, {"restored_start": start_s, "restored_end": end_s}
