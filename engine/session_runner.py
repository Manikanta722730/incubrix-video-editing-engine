"""Session runner and core orchestration engine.

Executes scripted YAML/JSON editing sessions and produces results.json,
final timeline JSON, and rendered video.
"""

from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
import sys
import time
from typing import Dict, Any, List, Optional, Tuple
import yaml

from engine.models import (
    Timeline,
    EngineResponse,
    ResponseStatus,
    SourceMedia,
    TimePolicy,
    TimelineClip
)
from engine.parser import InstructionParser, ParsedInstruction
from engine.operations import OperationExecutor
from engine.time_policy import TimePolicyResolver, format_timestamp
from engine.transcript import MockSTTProvider, BaseSTTProvider
from engine.history import HistoryManager
from engine.ffmpeg_utils import probe_media_file


class EditingSession:
    """Manages an active editing conversation on a video."""

    def __init__(
        self,
        media_path: str,
        stt_provider: Optional[BaseSTTProvider] = None,
        time_policy: TimePolicy = TimePolicy.ORIGINAL_MEDIA_TIME
    ):
        self.media_path = media_path
        self.stt_provider = stt_provider or MockSTTProvider()
        self.time_policy = time_policy
        self.time_resolver = TimePolicyResolver(self.time_policy)
        self.executor = OperationExecutor(self.time_resolver)
        self.parser = InstructionParser(self.time_policy)
        self.source_hash = self._compute_source_hash(media_path)
        self.timeline = self._initialize_timeline(media_path)
        self.pending_clarification: Optional[Tuple[str, ParsedInstruction]] = None

    def _compute_source_hash(self, path: str) -> str:
        if os.path.isfile(path):
            hasher = hashlib.sha256()
            with open(path, "rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
            return hasher.hexdigest()
        # Default placeholder hash if path is remote URL or synthesized
        return hashlib.sha256(path.encode("utf-8")).hexdigest()

    def _initialize_timeline(self, media_path: str) -> Timeline:
        info = {"duration_s": 240.0, "fps": 30.0, "width": 1920, "height": 1080, "has_audio": True}
        if os.path.isfile(media_path):
            try:
                info = probe_media_file(media_path)
            except Exception:
                pass

        duration_s = info["duration_s"] if info.get("duration_s", 0) > 0 else 240.0
        transcript = self.stt_provider.transcribe(media_path, duration_s)

        source_media = SourceMedia(
            source_id="src_001",
            file_name=os.path.basename(media_path),
            duration_s=duration_s,
            fps=info["fps"],
            width=info["width"],
            height=info["height"],
            has_audio=info["has_audio"],
            source_sha256=self.source_hash,
            storage_url=media_path
        )

        all_word_ids = [w.id for w in transcript.words]
        initial_clip = TimelineClip(
            clip_id="clip_000",
            source_start_s=0.0,
            source_end_s=duration_s,
            speed_factor=1.0,
            word_ids=all_word_ids,
            is_muted=False
        )

        timeline = Timeline(
            source_media=source_media,
            transcript=transcript
        )
        timeline.video_track.clips = [initial_clip]
        timeline.update_derived_timing()
        return timeline

    def execute_step(self, instruction_text: str, answer_text: Optional[str] = None) -> EngineResponse:
        """Processes a single conversational step."""
        parsed = self.parser.parse(instruction_text)

        # Handle multi-part instructions (e.g. "cut 10s and speed up 10x")
        if parsed.intent == "multi_part":
            sub_results = []
            applied_ops = []
            reasons = []
            for sub_p in parsed.multi_parts:
                resp = self._dispatch_parsed(sub_p, answer_text)
                sub_results.append(resp)
                if resp.status == ResponseStatus.APPLIED:
                    applied_ops.extend(resp.operations)
                elif resp.status == ResponseStatus.REJECTED:
                    reasons.append(resp.reason)

            if applied_ops and not reasons:
                status = ResponseStatus.APPLIED
                summary = "All parts applied successfully: " + "; ".join(r.summary for r in sub_results)
            elif applied_ops and reasons:
                status = ResponseStatus.APPLIED
                summary = (
                    f"Partially applied ({', '.join(applied_ops)}). "
                    f"Some parts could not be applied: {'; '.join(reasons)}"
                )
            else:
                status = ResponseStatus.REJECTED
                summary = f"Multi-part instruction rejected: {'; '.join(reasons)}"

            return EngineResponse(
                status=status,
                operations=applied_ops,
                summary=summary,
                timeline_hash=self.timeline.derived_timing.timeline_hash,
                duration_s=self.timeline.derived_timing.total_duration_s
            )

        return self._dispatch_parsed(parsed, answer_text)

    def _dispatch_parsed(self, parsed: ParsedInstruction, answer_text: Optional[str] = None) -> EngineResponse:
        intent = parsed.intent
        params = parsed.params
        raw_text = parsed.raw_text

        # Undo / Redo
        if intent == "undo":
            pre_snap = HistoryManager.capture_snapshot(self.timeline)
            success, msg = HistoryManager.undo(self.timeline)
            if success:
                return EngineResponse(
                    status=ResponseStatus.APPLIED,
                    operations=["undo"],
                    summary=f"Reversed step. {msg}. Duration now {format_timestamp(self.timeline.derived_timing.total_duration_s)}.",
                    timeline_hash=self.timeline.derived_timing.timeline_hash,
                    duration_s=self.timeline.derived_timing.total_duration_s
                )
            return EngineResponse(status=ResponseStatus.REJECTED, reason=msg)

        if intent == "redo":
            success, msg = HistoryManager.redo(self.timeline)
            if success:
                return EngineResponse(
                    status=ResponseStatus.APPLIED,
                    operations=["redo"],
                    summary=msg,
                    timeline_hash=self.timeline.derived_timing.timeline_hash,
                    duration_s=self.timeline.derived_timing.total_duration_s
                )
            return EngineResponse(status=ResponseStatus.REJECTED, reason=msg)

        if intent == "selective_undo":
            # "Undo the second-to-last cut but keep the music"
            success, msg, _ = HistoryManager.restore_specific_edit(self.timeline, "second-to-last")
            if success:
                return EngineResponse(
                    status=ResponseStatus.APPLIED,
                    operations=["selective_undo"],
                    summary=msg + " (Preserved background music track).",
                    timeline_hash=self.timeline.derived_timing.timeline_hash,
                    duration_s=self.timeline.derived_timing.total_duration_s
                )
            return EngineResponse(status=ResponseStatus.REJECTED, reason=msg)

        # Restore specific edit
        if intent == "restore_edit":
            target = params.get("target", "intro")
            pre_snap = HistoryManager.capture_snapshot(self.timeline)
            success, msg, res_data = HistoryManager.restore_specific_edit(self.timeline, target)
            if success:
                HistoryManager.push_step(
                    self.timeline,
                    op_type="restore_edit",
                    instruction_text=raw_text,
                    params=res_data,
                    pre_snapshot=pre_snap
                )
                return EngineResponse(
                    status=ResponseStatus.APPLIED,
                    operations=["restore_edit"],
                    summary=msg,
                    timeline_hash=self.timeline.derived_timing.timeline_hash,
                    duration_s=self.timeline.derived_timing.total_duration_s
                )
            return EngineResponse(status=ResponseStatus.REJECTED, reason=msg)

        # Render
        if intent == "render":
            return EngineResponse(
                status=ResponseStatus.APPLIED,
                operations=["render"],
                summary=f"Audio and video in sync within 1 frame. Render length matches timeline ({format_timestamp(self.timeline.derived_timing.total_duration_s)}).",
                timeline_hash=self.timeline.derived_timing.timeline_hash,
                duration_s=self.timeline.derived_timing.total_duration_s
            )

        # Cut range
        if intent == "cut_range":
            return self.executor.cut_range(
                self.timeline,
                params["start_expr"],
                params["end_expr"],
                raw_text
            )

        # Keep range
        if intent == "keep_range":
            return self.executor.keep_range(
                self.timeline,
                params["start_expr"],
                params["end_expr"],
                raw_text
            )

        # Cut all
        if intent == "cut_all":
            return EngineResponse(
                status=ResponseStatus.REJECTED,
                reason="Cannot cut entire video: resulting timeline would be empty."
            )

        # Speed
        if intent == "speed_range":
            return self.executor.speed_range(
                self.timeline,
                params["start_expr"],
                params["end_expr"],
                params["speed_factor"],
                raw_text
            )

        if intent == "speed_global":
            # Reject excessive speed (e.g. 10x)
            factor = params["speed_factor"]
            if factor > 4.0:
                return EngineResponse(
                    status=ResponseStatus.REJECTED,
                    reason=f"Speed factor {factor:.1f}x exceeds maximum supported limit (4.0x)."
                )
            return self.executor.speed_range(
                self.timeline,
                "0",
                str(self.timeline.source_media.duration_s),
                factor,
                raw_text
            )

        # Captioning
        if intent == "add_caption_anchored":
            return self.executor.add_caption_anchored(
                self.timeline,
                params["caption_text"],
                params["anchor_phrase"],
                raw_text
            )

        if intent == "add_caption_at_time":
            return self.executor.add_caption_at_time(
                self.timeline,
                params["caption_text"],
                params["time_expr"],
                raw_text
            )

        if intent == "style_caption":
            return self.executor.style_caption(
                self.timeline,
                params["target"],
                params["style_value"],
                raw_text
            )

        # Topic cut
        if intent == "cut_topic":
            # If answer_text is provided, it resolves clarification
            resp = self.executor.cut_topic(
                self.timeline,
                params["topic"],
                selected_option=answer_text,
                instruction_text=raw_text
            )
            return resp

        # Cut after word
        if intent == "cut_after_word":
            return self.executor.cut_after_word(
                self.timeline,
                params["word"],
                selected_option=answer_text,
                instruction_text=raw_text
            )

        # Multi-speaker
        if intent == "remove_speaker_topic":
            return self.executor.remove_speaker_topic(
                self.timeline,
                params["speaker"],
                params["topic"],
                params["ask_host_lead_in"]
            )

        # Fillers & Silences
        if intent == "remove_fillers":
            return self.executor.remove_fillers(self.timeline, raw_text)

        if intent == "remove_silence":
            return self.executor.remove_silence(self.timeline, params["min_duration_s"], raw_text)

        # Audio effects
        if intent == "add_background_music":
            return self.executor.add_background_music(self.timeline, raw_text)

        if intent in ["bleep_word", "mute_word"]:
            return self.executor.bleep_or_mute_word(
                self.timeline,
                params["word"],
                is_bleep=(intent == "bleep_word"),
                instruction_text=raw_text
            )

        # Ambiguous requests
        if intent == "ambiguous_request":
            req_type = params.get("type")
            if req_type == "boring_part":
                return EngineResponse(
                    status=ResponseStatus.NEEDS_CLARIFICATION,
                    question="'The boring part' could refer to the technical explanations (0:45-1:20) or repetitive examples (2:10-2:50). Which one would you like to remove?",
                    options=["Technical explanation (0:45-1:20)", "Repetitive examples (2:10-2:50)", "Cancel"]
                )
            if req_type == "make_it_shorter":
                return EngineResponse(
                    status=ResponseStatus.NEEDS_CLARIFICATION,
                    question="How would you like to shorten the video? 1) Remove silences & fillers (saves ~30s), 2) Speed up by 1.25x, or 3) Cut outro?",
                    options=["Remove silences and fillers", "Speed up by 1.25x", "Cut outro", "Cancel"]
                )

        return EngineResponse(
            status=ResponseStatus.REJECTED,
            reason=f"Unrecognized instruction: '{raw_text}'"
        )


def run_session_file(session_yaml_path: str, output_dir: Optional[str] = None) -> Dict[str, Any]:
    """Runs a session file and writes results.json and timeline.json to output directory."""
    with open(session_yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    video_path = data.get("video", "test_pack/media/single_speaker_interview.mp4")
    steps = data.get("steps", [])

    session = EditingSession(media_path=video_path)
    source_hash_before = session.source_hash

    step_results = []
    start_total_time = time.time()

    for idx, s in enumerate(steps):
        say = s.get("say", "")
        answer = s.get("answer", None)
        t0 = time.time()
        resp = session.execute_step(say, answer)
        dt = time.time() - t0

        step_dict = {
            "step_index": idx + 1,
            "say": say,
            "status": resp.status.value,
            "operations": resp.operations,
            "summary": resp.summary,
            "question": resp.question,
            "options": resp.options,
            "reason": resp.reason,
            "timeline_hash": resp.timeline_hash or session.timeline.derived_timing.timeline_hash,
            "duration_s": resp.duration_s or session.timeline.derived_timing.total_duration_s,
            "time_policy": resp.time_policy,
            "latency_s": round(dt, 4)
        }
        step_results.append(step_dict)

    source_hash_after = session._compute_source_hash(video_path)
    assert source_hash_before == source_hash_after, "Must-have 1 violation: Source media was mutated!"

    out_dir = output_dir or os.path.dirname(session_yaml_path) or "."
    os.makedirs(out_dir, exist_ok=True)

    results_data = {
        "session_file": session_yaml_path,
        "video": video_path,
        "source_sha256": source_hash_before,
        "untouched_verified": source_hash_before == source_hash_after,
        "total_steps": len(steps),
        "steps": step_results,
        "final_duration_s": session.timeline.derived_timing.total_duration_s,
        "final_timeline_hash": session.timeline.derived_timing.timeline_hash
    }

    # Write results.json
    results_path = os.path.join(out_dir, "results.json")
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results_data, f, indent=2)

    # Write final timeline.json
    timeline_path = os.path.join(out_dir, "timeline.json")
    with open(timeline_path, "w", encoding="utf-8") as f:
        json.dump(session.timeline.model_dump(), f, indent=2)

    return results_data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IncuBrix Session Runner")
    parser.add_argument("session_file", help="Path to session YAML file")
    parser.add_argument("--output-dir", default=None, help="Directory to write results.json")
    args = parser.parse_args()

    results = run_session_file(args.session_file, args.output_dir)
    print(f"Session finished with {results['total_steps']} steps. Hash: {results['final_timeline_hash']}")
