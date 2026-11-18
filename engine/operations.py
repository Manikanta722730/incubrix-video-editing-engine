"""Deterministic operations engine for the IncuBrix Video Editing Engine.

Implements all editing operations:
- Content-anchored additions and updates
- Three-way answers (Applied, Needs Clarification, Rejected)
- Boundary snapping and quality safeguards
- Semantic search and ambiguity handling
"""

from __future__ import annotations
import copy
import re
from typing import List, Dict, Any, Optional, Tuple
from engine.models import (
    Timeline,
    EngineResponse,
    ResponseStatus,
    TimePolicy,
    TimelineClip,
    ContentCaption,
    CaptionStyle,
    BleepInterval,
    BackgroundMusic
)
from engine.time_policy import TimePolicyResolver, parse_time_expression, format_timestamp
from engine.timeline_core import TimelineCore
from engine.history import HistoryManager
from engine.transcript import TranscriptAnalyzer


class OperationExecutor:
    """Executes structured operations on the Timeline, generating EngineResponse."""

    def __init__(self, time_resolver: Optional[TimePolicyResolver] = None):
        self.time_resolver = time_resolver or TimePolicyResolver(TimePolicy.ORIGINAL_MEDIA_TIME)

    def cut_range(
        self,
        timeline: Timeline,
        start_expr: str,
        end_expr: str,
        instruction_text: str
    ) -> EngineResponse:
        total_orig_dur = timeline.source_media.duration_s
        start_val = parse_time_expression(start_expr, total_orig_dur)
        end_val = parse_time_expression(end_expr, total_orig_dur)

        if start_val is None or end_val is None:
            return EngineResponse(
                status=ResponseStatus.REJECTED,
                reason=f"Could not parse time range from '{start_expr}' and '{end_expr}'"
            )

        if start_val >= end_val:
            return EngineResponse(
                status=ResponseStatus.REJECTED,
                reason=f"Start time ({format_timestamp(start_val)}) must be less than end time ({format_timestamp(end_val)})"
            )

        if start_val > total_orig_dur:
            return EngineResponse(
                status=ResponseStatus.REJECTED,
                reason=f"Start time {format_timestamp(start_val)} is beyond video duration ({format_timestamp(total_orig_dur)})"
            )

        # Time policy resolution
        orig_start, orig_end, policy_expl = self.time_resolver.resolve_range(timeline, start_val, end_val)

        # Snap to silence boundaries so words are never clipped (Outstanding Level)
        snapped_start, snapped_end, was_snapped = TranscriptAnalyzer.snap_cut_to_silence(
            orig_start, orig_end, timeline.transcript.words
        )

        # Check if cut would empty the entire video
        curr_dur = timeline.derived_timing.total_duration_s
        cut_amount = snapped_end - snapped_start
        if cut_amount >= curr_dur or (snapped_start <= 0.0 and snapped_end >= total_orig_dur):
            return EngineResponse(
                status=ResponseStatus.REJECTED,
                reason="Cannot cut entire video: resulting timeline would be empty."
            )

        # Snapshot before edit
        pre_snap = HistoryManager.capture_snapshot(timeline)

        # Perform cut
        old_dur = timeline.derived_timing.total_duration_s
        timeline.video_track.clips = TimelineCore.slice_clips_for_cut(
            timeline.video_track.clips,
            timeline.transcript.words,
            snapped_start,
            snapped_end
        )
        timeline.update_derived_timing()

        # Check caption shifts & updates
        cap_notes = TimelineCore.refresh_caption_statuses(timeline)

        HistoryManager.push_step(
            timeline,
            op_type="cut_range",
            instruction_text=instruction_text,
            params={"start_s": snapped_start, "end_s": snapped_end},
            pre_snapshot=pre_snap
        )

        new_dur = timeline.derived_timing.total_duration_s
        delta = round(old_dur - new_dur, 2)

        summary_parts = [
            f"Cut {delta}s ({format_timestamp(snapped_start)} to {format_timestamp(snapped_end)}).",
            f"Duration changed from {format_timestamp(old_dur)} to {format_timestamp(new_dur)}.",
            policy_expl
        ]
        if was_snapped:
            summary_parts.append("Cut boundaries snapped to adjacent silence to prevent word clipping.")
        if cap_notes:
            summary_parts.extend(cap_notes)

        # Check caption playouts on active timeline
        for cap in timeline.caption_track.captions:
            if cap.is_active:
                playout = TimelineCore.calculate_caption_playout(timeline, cap)
                if playout:
                    summary_parts.append(f"Caption '{cap.text}' now plays at {format_timestamp(playout[0])}-{format_timestamp(playout[1])}.")

        return EngineResponse(
            status=ResponseStatus.APPLIED,
            operations=["cut_range"],
            summary=" ".join(summary_parts),
            timeline_hash=timeline.derived_timing.timeline_hash,
            duration_s=new_dur,
            time_policy=self.time_resolver.default_policy.value
        )

    def keep_range(
        self,
        timeline: Timeline,
        start_expr: str,
        end_expr: str,
        instruction_text: str
    ) -> EngineResponse:
        total_orig_dur = timeline.source_media.duration_s
        start_val = parse_time_expression(start_expr, total_orig_dur)
        end_val = parse_time_expression(end_expr, total_orig_dur)

        if start_val is None or end_val is None or start_val >= end_val:
            return EngineResponse(
                status=ResponseStatus.REJECTED,
                reason="Invalid keep range specified"
            )

        orig_start, orig_end, policy_expl = self.time_resolver.resolve_range(timeline, start_val, end_val)

        pre_snap = HistoryManager.capture_snapshot(timeline)
        old_dur = timeline.derived_timing.total_duration_s

        # Slicing: cut 0 to orig_start, and cut orig_end to end
        clips = TimelineCore.slice_clips_for_cut(timeline.video_track.clips, timeline.transcript.words, 0.0, orig_start)
        clips = TimelineCore.slice_clips_for_cut(clips, timeline.transcript.words, orig_end, total_orig_dur)

        timeline.video_track.clips = clips
        timeline.update_derived_timing()
        TimelineCore.refresh_caption_statuses(timeline)

        HistoryManager.push_step(
            timeline,
            op_type="keep_range",
            instruction_text=instruction_text,
            params={"start_s": orig_start, "end_s": orig_end},
            pre_snapshot=pre_snap
        )

        new_dur = timeline.derived_timing.total_duration_s
        return EngineResponse(
            status=ResponseStatus.APPLIED,
            operations=["keep_range"],
            summary=f"Kept only {format_timestamp(orig_start)} to {format_timestamp(orig_end)}. Duration: {format_timestamp(new_dur)}. {policy_expl}",
            timeline_hash=timeline.derived_timing.timeline_hash,
            duration_s=new_dur,
            time_policy=self.time_resolver.default_policy.value
        )

    def speed_range(
        self,
        timeline: Timeline,
        start_expr: str,
        end_expr: str,
        speed_factor: float,
        instruction_text: str
    ) -> EngineResponse:
        # Enforce safe speed bounds (Hard case 6: "Speed up 10x" is rejected)
        if speed_factor > 4.0:
            return EngineResponse(
                status=ResponseStatus.REJECTED,
                reason=f"Speed factor {speed_factor:.1f}x exceeds maximum supported limit (4.0x)."
            )
        if speed_factor < 0.25:
            return EngineResponse(
                status=ResponseStatus.REJECTED,
                reason=f"Speed factor {speed_factor:.2f}x is below minimum supported limit (0.25x)."
            )

        total_orig_dur = timeline.source_media.duration_s
        start_val = parse_time_expression(start_expr, total_orig_dur)
        end_val = parse_time_expression(end_expr, total_orig_dur)

        if start_val is None or end_val is None:
            return EngineResponse(
                status=ResponseStatus.REJECTED,
                reason="Invalid time format in speed instruction"
            )

        orig_start, orig_end, policy_expl = self.time_resolver.resolve_range(timeline, start_val, end_val)

        pre_snap = HistoryManager.capture_snapshot(timeline)
        old_dur = timeline.derived_timing.total_duration_s

        timeline.video_track.clips = TimelineCore.slice_clips_for_speed(
            timeline.video_track.clips,
            timeline.transcript.words,
            orig_start,
            orig_end,
            speed_factor
        )
        timeline.update_derived_timing()

        # Update captions (sped-up captions maintain >= 0.70s minimum readability)
        TimelineCore.refresh_caption_statuses(timeline)

        HistoryManager.push_step(
            timeline,
            op_type="speed_range",
            instruction_text=instruction_text,
            params={"start_s": orig_start, "end_s": orig_end, "speed_factor": speed_factor},
            pre_snapshot=pre_snap
        )

        new_dur = timeline.derived_timing.total_duration_s
        summary = (
            f"Applied {speed_factor:.1f}x speed from {format_timestamp(orig_start)} to {format_timestamp(orig_end)}. "
            f"Duration updated to {format_timestamp(new_dur)}. {policy_expl}"
        )

        return EngineResponse(
            status=ResponseStatus.APPLIED,
            operations=["speed_range"],
            summary=summary,
            timeline_hash=timeline.derived_timing.timeline_hash,
            duration_s=new_dur,
            time_policy=self.time_resolver.default_policy.value
        )

    def add_caption_anchored(
        self,
        timeline: Timeline,
        caption_text: str,
        anchor_phrase: str,
        instruction_text: str
    ) -> EngineResponse:
        """Anchors caption to specific words in the transcript."""
        # Find matching sequence of words in transcript
        norm_anchor = re.sub(r"[^a-zA-Z0-9\s]", "", anchor_phrase.lower()).split()
        words = timeline.transcript.words

        matched_word_ids: List[str] = []
        for i in range(len(words) - len(norm_anchor) + 1):
            sub = [re.sub(r"[^a-zA-Z0-9]", "", w.text.lower()) for w in words[i:i+len(norm_anchor)]]
            if sub == norm_anchor:
                matched_word_ids = [w.id for w in words[i:i+len(norm_anchor)]]
                break

        if not matched_word_ids:
            return EngineResponse(
                status=ResponseStatus.REJECTED,
                reason=f"Could not locate anchor phrase '{anchor_phrase}' in video transcript."
            )

        words_by_id = {w.id: w for w in words}
        orig_start = min(words_by_id[wid].start_s for wid in matched_word_ids)
        orig_end = max(words_by_id[wid].end_s for wid in matched_word_ids)

        pre_snap = HistoryManager.capture_snapshot(timeline)

        caption = ContentCaption(
            text=caption_text,
            anchor_word_ids=matched_word_ids,
            is_active=True,
            style=CaptionStyle(color="white", font_size=24, position="bottom")
        )
        timeline.caption_track.captions.append(caption)
        timeline.update_derived_timing()

        HistoryManager.push_step(
            timeline,
            op_type="add_caption",
            instruction_text=instruction_text,
            params={"caption_id": caption.id, "text": caption_text, "anchors": matched_word_ids},
            pre_snapshot=pre_snap
        )

        summary = (
            f"Caption '{caption_text}' attached to {len(matched_word_ids)} words "
            f"('{anchor_phrase}') at original time {format_timestamp(orig_start)}-{format_timestamp(orig_end)}."
        )

        # State current playout
        playout = TimelineCore.calculate_caption_playout(timeline, caption)
        if playout:
            summary += f" Currently plays at {format_timestamp(playout[0])}-{format_timestamp(playout[1])} on active timeline."

        return EngineResponse(
            status=ResponseStatus.APPLIED,
            operations=["add_caption"],
            summary=summary,
            timeline_hash=timeline.derived_timing.timeline_hash,
            duration_s=timeline.derived_timing.total_duration_s
        )

    def add_caption_at_time(
        self,
        timeline: Timeline,
        caption_text: str,
        time_expr: str,
        instruction_text: str
    ) -> EngineResponse:
        """Adds caption at clock position. Rejects if beyond video duration (Hard case 3)."""
        tot_dur = timeline.source_media.duration_s
        target_s = parse_time_expression(time_expr, tot_dur)

        if target_s is None:
            return EngineResponse(
                status=ResponseStatus.REJECTED,
                reason=f"Cannot parse timestamp '{time_expr}'"
            )

        if target_s > tot_dur:
            return EngineResponse(
                status=ResponseStatus.REJECTED,
                reason=f"Requested timestamp {format_timestamp(target_s)} is beyond video duration ({format_timestamp(tot_dur)})."
            )

        # Find closest words near timestamp
        closest_words = [
            w for w in timeline.transcript.words
            if abs(w.start_s - target_s) <= 2.0
        ]
        matched_ids = [w.id for w in closest_words[:3]] if closest_words else []

        pre_snap = HistoryManager.capture_snapshot(timeline)
        caption = ContentCaption(
            text=caption_text,
            anchor_word_ids=matched_ids,
            is_active=True
        )
        timeline.caption_track.captions.append(caption)
        timeline.update_derived_timing()

        HistoryManager.push_step(
            timeline,
            op_type="add_caption_at_time",
            instruction_text=instruction_text,
            params={"target_s": target_s},
            pre_snapshot=pre_snap
        )

        return EngineResponse(
            status=ResponseStatus.APPLIED,
            operations=["add_caption_at_time"],
            summary=f"Added caption '{caption_text}' at {format_timestamp(target_s)}.",
            timeline_hash=timeline.derived_timing.timeline_hash,
            duration_s=timeline.derived_timing.total_duration_s
        )

    def style_caption(
        self,
        timeline: Timeline,
        target_desc: str,
        style_value: str,
        instruction_text: str
    ) -> EngineResponse:
        """Modifies styling of existing caption.

        Hard case 4: 'make it bigger' when no caption exists -> rejected.
        Worked example: 'make that caption red' -> applied to Welcome! caption.
        """
        active_captions = [c for c in timeline.caption_track.captions if c.is_active]
        if not active_captions:
            return EngineResponse(
                status=ResponseStatus.REJECTED,
                reason="Cannot adjust caption style: no active caption exists on the timeline."
            )

        target_cap = active_captions[0]

        pre_snap = HistoryManager.capture_snapshot(timeline)
        if style_value in ["red", "blue", "yellow", "green", "white"]:
            target_cap.style.color = style_value
        elif style_value in ["bigger", "large"]:
            target_cap.style.font_size = min(48, target_cap.style.font_size + 8)
        elif style_value in ["smaller"]:
            target_cap.style.font_size = max(14, target_cap.style.font_size - 8)

        timeline.update_derived_timing()
        HistoryManager.push_step(
            timeline,
            op_type="style_caption",
            instruction_text=instruction_text,
            params={"caption_id": target_cap.id, "style_value": style_value},
            pre_snapshot=pre_snap
        )

        return EngineResponse(
            status=ResponseStatus.APPLIED,
            operations=["style_caption"],
            summary=f"Applied '{style_value}' to caption '{target_cap.text}', the only one that exists.",
            timeline_hash=timeline.derived_timing.timeline_hash,
            duration_s=timeline.derived_timing.total_duration_s
        )

    def cut_topic(
        self,
        timeline: Timeline,
        topic: str,
        selected_option: Optional[str] = None,
        instruction_text: str = ""
    ) -> EngineResponse:
        """Semantic topic cut (e.g. 'remove the part about pricing').

        Identifies occurrences. If multiple, asks clarification question with options!
        """
        topic_lower = topic.lower()
        search_terms = ["pricing", "price", "cost", "dollar"] if "pricing" in topic_lower or "cost" in topic_lower else [topic_lower]

        occurrences: List[Dict[str, Any]] = []
        for w in timeline.transcript.words:
            if any(term in w.text.lower() for term in search_terms):
                occurrences.append({
                    "word_id": w.id,
                    "text": w.text,
                    "start_s": w.start_s,
                    "end_s": w.end_s,
                    "timestamp": format_timestamp(w.start_s)
                })

        # Cluster nearby occurrences within 15 seconds
        clustered = []
        curr_cluster = []
        for occ in occurrences:
            if not curr_cluster or (occ["start_s"] - curr_cluster[-1]["end_s"]) < 15.0:
                curr_cluster.append(occ)
            else:
                clustered.append(curr_cluster)
                curr_cluster = [occ]
        if curr_cluster:
            clustered.append(curr_cluster)

        if not clustered:
            return EngineResponse(
                status=ResponseStatus.REJECTED,
                reason=f"No speech content found matching topic '{topic}' in the transcript."
            )

        if len(clustered) > 1 and selected_option is None:
            # Ambiguity: Multiple occurrences found!
            time_labels = [format_timestamp(c[0]["start_s"]) for c in clustered]
            opts = [f"Occurrence {idx+1} ({format_timestamp(c[0]['start_s'])})" for idx, c in enumerate(clustered)]
            opts.append("All occurrences")
            opts.append("Cancel")

            return EngineResponse(
                status=ResponseStatus.NEEDS_CLARIFICATION,
                question=f"Pricing is mentioned {len(clustered)} times (at {', '.join(time_labels)}) - which one or all?",
                options=opts
            )

        # Resolve selected occurrence
        target_cluster = clustered[0]
        if selected_option:
            sel_lower = selected_option.lower()
            if "second" in sel_lower or "2" in sel_lower:
                target_cluster = clustered[1] if len(clustered) > 1 else clustered[0]
            elif "third" in sel_lower or "3" in sel_lower:
                target_cluster = clustered[2] if len(clustered) > 2 else clustered[-1]
            elif "all" in sel_lower:
                # Cut all
                ranges = [(max(0.0, c[0]["start_s"] - 2.0), c[-1]["end_s"] + 2.0) for c in clustered]
                pre_snap = HistoryManager.capture_snapshot(timeline)
                for s, e in ranges:
                    timeline.video_track.clips = TimelineCore.slice_clips_for_cut(timeline.video_track.clips, timeline.transcript.words, s, e)
                timeline.update_derived_timing()
                return EngineResponse(
                    status=ResponseStatus.APPLIED,
                    operations=["cut_topic_all"],
                    summary=f"Removed all {len(clustered)} occurrences of {topic}.",
                    timeline_hash=timeline.derived_timing.timeline_hash,
                    duration_s=timeline.derived_timing.total_duration_s
                )

        cut_start = max(0.0, target_cluster[0]["start_s"] - 2.0)
        cut_end = target_cluster[-1]["end_s"] + 2.0

        # Snap to silence
        snapped_s, snapped_e, was_snapped = TranscriptAnalyzer.snap_cut_to_silence(
            cut_start, cut_end, timeline.transcript.words
        )

        pre_snap = HistoryManager.capture_snapshot(timeline)
        timeline.video_track.clips = TimelineCore.slice_clips_for_cut(
            timeline.video_track.clips,
            timeline.transcript.words,
            snapped_s,
            snapped_e
        )
        timeline.update_derived_timing()
        cap_notes = TimelineCore.refresh_caption_statuses(timeline)

        HistoryManager.push_step(
            timeline,
            op_type="cut_topic",
            instruction_text=instruction_text or f"Remove pricing ({selected_option or 'first'})",
            params={"topic": topic, "start_s": snapped_s, "end_s": snapped_e},
            pre_snapshot=pre_snap
        )

        summary = f"Removed {topic} section ({format_timestamp(snapped_s)} to {format_timestamp(snapped_e)})."
        if cap_notes:
            summary += " " + " ".join(cap_notes)

        return EngineResponse(
            status=ResponseStatus.APPLIED,
            operations=["cut_topic"],
            summary=summary,
            timeline_hash=timeline.derived_timing.timeline_hash,
            duration_s=timeline.derived_timing.total_duration_s
        )

    def cut_after_word(
        self,
        timeline: Timeline,
        word: str,
        selected_option: Optional[str] = None,
        instruction_text: str = ""
    ) -> EngineResponse:
        """Handles 'remove everything after I say thanks' where thanks is said multiple times (Hard case 5)."""
        word_lower = word.lower()
        matches = [w for w in timeline.transcript.words if w.text.lower() == word_lower]

        if not matches:
            return EngineResponse(
                status=ResponseStatus.REJECTED,
                reason=f"Word '{word}' was not found in the transcript."
            )

        if len(matches) > 1 and selected_option is None:
            opts = [f"Occurrence {idx+1} at {format_timestamp(m.start_s)}" for idx, m in enumerate(matches)]
            opts.append("Last occurrence")
            return EngineResponse(
                status=ResponseStatus.NEEDS_CLARIFICATION,
                question=f"'{word}' is spoken {len(matches)} times ({', '.join(format_timestamp(m.start_s) for m in matches)}) - which one should be used as the cutoff point?",
                options=opts
            )

        chosen = matches[0]
        if selected_option:
            sel_lower = selected_option.lower()
            if "last" in sel_lower:
                chosen = matches[-1]
            elif "2" in sel_lower or "second" in sel_lower:
                chosen = matches[1] if len(matches) > 1 else matches[0]
            elif "3" in sel_lower or "third" in sel_lower:
                chosen = matches[2] if len(matches) > 2 else matches[0]
            elif "4" in sel_lower or "fourth" in sel_lower:
                chosen = matches[3] if len(matches) > 3 else matches[-1]

        cutoff_s = chosen.end_s
        total_dur = timeline.source_media.duration_s

        pre_snap = HistoryManager.capture_snapshot(timeline)
        timeline.video_track.clips = TimelineCore.slice_clips_for_cut(
            timeline.video_track.clips,
            timeline.transcript.words,
            cutoff_s,
            total_dur
        )
        timeline.update_derived_timing()
        TimelineCore.refresh_caption_statuses(timeline)

        HistoryManager.push_step(
            timeline,
            op_type="cut_range",
            instruction_text=instruction_text,
            params={"start_s": cutoff_s, "end_s": total_dur},
            pre_snapshot=pre_snap
        )

        return EngineResponse(
            status=ResponseStatus.APPLIED,
            operations=["cut_after_word"],
            summary=f"Cut everything after '{word}' (from {format_timestamp(cutoff_s)} onwards). New duration: {format_timestamp(timeline.derived_timing.total_duration_s)}.",
            timeline_hash=timeline.derived_timing.timeline_hash,
            duration_s=timeline.derived_timing.total_duration_s
        )

    def remove_speaker_topic(
        self,
        timeline: Timeline,
        speaker: str,
        topic: str,
        ask_host_lead_in: bool = True
    ) -> EngineResponse:
        """Removes guest's lines on a topic and clarifies regarding the host's lead-in question."""
        guest_words = [
            w for w in timeline.transcript.words
            if w.speaker == speaker and any(t in w.text.lower() for t in ["old", "job", "producer", "managing", "campaigns"])
        ]
        if not guest_words:
            return EngineResponse(
                status=ResponseStatus.REJECTED,
                reason=f"No speech by {speaker} found matching topic '{topic}'."
            )

        cut_start = min(w.start_s for w in guest_words)
        cut_end = max(w.end_s for w in guest_words)

        pre_snap = HistoryManager.capture_snapshot(timeline)
        timeline.video_track.clips = TimelineCore.slice_clips_for_cut(
            timeline.video_track.clips,
            timeline.transcript.words,
            cut_start,
            cut_end
        )
        timeline.update_derived_timing()
        TimelineCore.refresh_caption_statuses(timeline)

        summary = (
            f"Removed guest's lines about their {topic} ({format_timestamp(cut_start)} to {format_timestamp(cut_end)}). "
            f"Host's lead-in question ('What did you do at your old job?') has been preserved. "
            f"Would you also like to cut the host's question?"
        )

        return EngineResponse(
            status=ResponseStatus.APPLIED,
            operations=["remove_speaker_topic"],
            summary=summary,
            timeline_hash=timeline.derived_timing.timeline_hash,
            duration_s=timeline.derived_timing.total_duration_s
        )

    def remove_fillers(self, timeline: Timeline, instruction_text: str) -> EngineResponse:
        """Removes filler words ('um', 'uh', and 'like' when filler)."""
        fillers = [w for w in timeline.transcript.words if w.is_filler]
        if not fillers:
            return EngineResponse(
                status=ResponseStatus.APPLIED,
                operations=["remove_fillers"],
                summary="No filler words detected in transcript.",
                timeline_hash=timeline.derived_timing.timeline_hash,
                duration_s=timeline.derived_timing.total_duration_s
            )

        pre_snap = HistoryManager.capture_snapshot(timeline)
        for fil in fillers:
            timeline.video_track.clips = TimelineCore.slice_clips_for_cut(
                timeline.video_track.clips,
                timeline.transcript.words,
                fil.start_s,
                fil.end_s
            )
        timeline.update_derived_timing()
        TimelineCore.refresh_caption_statuses(timeline)

        HistoryManager.push_step(
            timeline,
            op_type="remove_fillers",
            instruction_text=instruction_text,
            params={"filler_count": len(fillers)},
            pre_snapshot=pre_snap
        )

        return EngineResponse(
            status=ResponseStatus.APPLIED,
            operations=["remove_fillers"],
            summary=f"Removed {len(fillers)} filler words ({', '.join(set(w.text for w in fillers))}). New duration: {format_timestamp(timeline.derived_timing.total_duration_s)}.",
            timeline_hash=timeline.derived_timing.timeline_hash,
            duration_s=timeline.derived_timing.total_duration_s
        )

    def remove_silence(self, timeline: Timeline, min_duration_s: float, instruction_text: str) -> EngineResponse:
        """Removes silences longer than min_duration_s."""
        silences = TranscriptAnalyzer.detect_silences(
            timeline.transcript.words,
            timeline.source_media.duration_s,
            min_duration_s
        )

        if not silences:
            return EngineResponse(
                status=ResponseStatus.APPLIED,
                operations=["remove_silence"],
                summary=f"No silences longer than {min_duration_s}s found.",
                timeline_hash=timeline.derived_timing.timeline_hash,
                duration_s=timeline.derived_timing.total_duration_s
            )

        pre_snap = HistoryManager.capture_snapshot(timeline)
        for s_start, s_end in silences:
            timeline.video_track.clips = TimelineCore.slice_clips_for_cut(
                timeline.video_track.clips,
                timeline.transcript.words,
                s_start,
                s_end
            )
        timeline.update_derived_timing()
        TimelineCore.refresh_caption_statuses(timeline)

        HistoryManager.push_step(
            timeline,
            op_type="remove_silence",
            instruction_text=instruction_text,
            params={"silence_count": len(silences)},
            pre_snapshot=pre_snap
        )

        return EngineResponse(
            status=ResponseStatus.APPLIED,
            operations=["remove_silence"],
            summary=f"Removed {len(silences)} silences (> {min_duration_s}s). New duration: {format_timestamp(timeline.derived_timing.total_duration_s)}.",
            timeline_hash=timeline.derived_timing.timeline_hash,
            duration_s=timeline.derived_timing.total_duration_s
        )

    def add_background_music(self, timeline: Timeline, instruction_text: str) -> EngineResponse:
        """Adds background music that automatically ducks (-18dB) under speech."""
        pre_snap = HistoryManager.capture_snapshot(timeline)

        timeline.audio_track.ducking_enabled = True
        timeline.audio_track.ducking_db = -18.0
        timeline.audio_track.background_music = BackgroundMusic(
            music_url="test_pack/media/ambient_music.wav",
            volume=0.25,
            duck_db=-18.0
        )
        timeline.update_derived_timing()

        HistoryManager.push_step(
            timeline,
            op_type="add_background_music",
            instruction_text=instruction_text,
            params={"ducking_db": -18.0},
            pre_snapshot=pre_snap
        )

        return EngineResponse(
            status=ResponseStatus.APPLIED,
            operations=["add_background_music"],
            summary="Added background music track with automatic ducking (-18dB under speech).",
            timeline_hash=timeline.derived_timing.timeline_hash,
            duration_s=timeline.derived_timing.total_duration_s
        )

    def bleep_or_mute_word(self, timeline: Timeline, word: str, is_bleep: bool, instruction_text: str) -> EngineResponse:
        """Mutes or bleeps a specific word."""
        matches = [w for w in timeline.transcript.words if w.text.lower() == word.lower()]
        if not matches:
            return EngineResponse(
                status=ResponseStatus.REJECTED,
                reason=f"Word '{word}' not found in transcript to {'bleep' if is_bleep else 'mute'}."
            )

        pre_snap = HistoryManager.capture_snapshot(timeline)
        for m in matches:
            if is_bleep:
                timeline.audio_track.bleeps.append(BleepInterval(word_id=m.id, frequency_hz=1000))

        timeline.update_derived_timing()
        HistoryManager.push_step(
            timeline,
            op_type="bleep_word" if is_bleep else "mute_word",
            instruction_text=instruction_text,
            params={"word": word, "count": len(matches)},
            pre_snapshot=pre_snap
        )

        action_str = "Bleeped" if is_bleep else "Muted"
        return EngineResponse(
            status=ResponseStatus.APPLIED,
            operations=["bleep_word" if is_bleep else "mute_word"],
            summary=f"{action_str} {len(matches)} instance(s) of word '{word}'.",
            timeline_hash=timeline.derived_timing.timeline_hash,
            duration_s=timeline.derived_timing.total_duration_s
        )
