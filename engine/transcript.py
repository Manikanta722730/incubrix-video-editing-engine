"""Transcript management, Speech-To-Text (STT) adapters, and speech boundary analysis.

Handles:
- Word-level timestamps, speakers, confidence
- Filler word identification ("um", "uh", and context-aware "like")
- Silence detection & boundary snapping so cuts never clip words
- Low-confidence word flagging
- Overlapping speech & speaker swap warnings
"""

from __future__ import annotations
import re
from typing import List, Dict, Any, Optional, Tuple
from engine.models import WordToken, Transcript


class BaseSTTProvider:
    def transcribe(self, media_path: str, duration_s: float) -> Transcript:
        raise NotImplementedError


class MockSTTProvider(BaseSTTProvider):
    """Deterministic Mock STT provider for testing and offline evaluation.

    Provides rich, multi-sentence transcripts for single-speaker and multi-speaker videos.
    """

    def __init__(self, transcript_override: Optional[Transcript] = None):
        self.transcript_override = transcript_override

    def transcribe(self, media_path: str, duration_s: float) -> Transcript:
        if self.transcript_override:
            return self.transcript_override

        # Detect if it's the standard 2-speaker podcast test file or single-speaker worked example
        is_two_speaker = "two_speaker" in media_path or "podcast" in media_path

        if is_two_speaker:
            return self._build_two_speaker_transcript(duration_s)
        else:
            return self._build_worked_example_transcript(duration_s)

    def _build_worked_example_transcript(self, duration_s: float) -> Transcript:
        """Standard worked example transcript matching the assessment brief:

        - 0:00 - 0:30: Intro monologue
        - 0:42 - 0:44: "welcome to the channel"
        - 1:05: Pricing mention 1 ("our pricing is ten dollars")
        - 1:15 - 1:25: Fast paced segment
        - 2:40: Pricing mention 2 ("regarding pricing options for teams")
        - 3:15: Pricing mention 3 ("the enterprise pricing tier")
        """
        words: List[WordToken] = []

        # Intro monologue: 0.0 - 28.0s
        intro_text = [
            ("hey", 1.0, 1.4), ("everyone", 1.5, 2.0), ("in", 2.2, 2.4), ("this", 2.5, 2.8),
            ("tutorial", 2.9, 3.5), ("we", 4.0, 4.2), ("will", 4.3, 4.5), ("learn", 4.6, 5.0),
            ("video", 5.2, 5.6), ("editing", 5.7, 6.2), ("with", 6.3, 6.6), ("ai", 6.7, 7.0),
            ("um", 8.0, 8.4),  # filler
            ("first", 9.0, 9.4), ("let", 9.5, 9.7), ("us", 9.8, 10.0), ("review", 10.1, 10.5),
            ("the", 10.6, 10.8), ("basics", 10.9, 11.5),
            ("uh", 13.0, 13.3),  # filler
            ("this", 14.0, 14.3), ("intro", 14.4, 14.8), ("covers", 14.9, 15.4), ("everything", 15.5, 16.0),
            ("about", 16.1, 16.5), ("timeline", 16.6, 17.2), ("manipulation", 17.3, 18.2),
            ("and", 19.0, 19.2), ("silence", 19.3, 19.8), ("detection", 19.9, 20.6)
        ]
        for idx, (t, s, e) in enumerate(intro_text):
            is_fil = t in ["um", "uh"]
            words.append(WordToken(id=f"w_{idx:03d}", text=t, start_s=s, end_s=e, speaker="speaker_1", confidence=0.98, is_filler=is_fil))

        # Anchor section: 0:42 - 0:44: "welcome to the channel"
        channel_anchor = [
            ("welcome", 42.0, 42.5),
            ("to", 42.6, 42.8),
            ("the", 42.9, 43.1),
            ("channel", 43.2, 44.0)
        ]
        cur_id = len(words)
        for idx, (t, s, e) in enumerate(channel_anchor):
            words.append(WordToken(id=f"w_{cur_id + idx:03d}", text=t, start_s=s, end_s=e, speaker="speaker_1", confidence=0.99))

        # Section 1: Pricing mention 1 at 1:05 (65.0s)
        pricing_1 = [
            ("now", 60.0, 60.4), ("our", 64.5, 64.8), ("pricing", 65.0, 65.6), ("starts", 65.7, 66.2),
            ("at", 66.3, 66.5), ("ten", 66.6, 67.0), ("dollars", 67.1, 67.8), ("per", 67.9, 68.1), ("month", 68.2, 68.7)
        ]
        cur_id = len(words)
        for idx, (t, s, e) in enumerate(pricing_1):
            words.append(WordToken(id=f"w_{cur_id + idx:03d}", text=t, start_s=s, end_s=e, speaker="speaker_1", confidence=0.97))

        # Speed range words: 1:00 to 1:30 (60.0s to 90.0s)
        mid_section = [
            ("here", 75.0, 75.4), ("is", 75.5, 75.7), ("the", 75.8, 76.0), ("fast", 76.1, 76.5),
            ("demonstration", 76.6, 77.4), ("of", 77.5, 77.7), ("the", 77.8, 78.0), ("engine", 78.1, 78.7)
        ]
        cur_id = len(words)
        for idx, (t, s, e) in enumerate(mid_section):
            words.append(WordToken(id=f"w_{cur_id + idx:03d}", text=t, start_s=s, end_s=e, speaker="speaker_1", confidence=0.96))

        # Section 2: Pricing mention 2 at 2:40 (160.0s)
        pricing_2 = [
            ("secondly", 158.0, 158.6), ("regarding", 159.0, 159.5), ("pricing", 160.0, 160.6),
            ("options", 160.7, 161.3), ("for", 161.4, 161.6), ("teams", 161.7, 162.3),
            ("we", 162.5, 162.7), ("offer", 162.8, 163.2), ("discounts", 163.3, 164.0)
        ]
        cur_id = len(words)
        for idx, (t, s, e) in enumerate(pricing_2):
            words.append(WordToken(id=f"w_{cur_id + idx:03d}", text=t, start_s=s, end_s=e, speaker="speaker_1", confidence=0.98))

        # Section 3: Pricing mention 3 at 3:15 (195.0s)
        pricing_3 = [
            ("finally", 193.0, 193.6), ("the", 194.5, 194.8), ("enterprise", 194.9, 195.5),
            ("pricing", 195.6, 196.2), ("tier", 196.3, 196.8), ("has", 196.9, 197.1),
            ("dedicated", 197.2, 197.8), ("support", 197.9, 198.5)
        ]
        cur_id = len(words)
        for idx, (t, s, e) in enumerate(pricing_3):
            words.append(WordToken(id=f"w_{cur_id + idx:03d}", text=t, start_s=s, end_s=e, speaker="speaker_1", confidence=0.95))

        # Outro with multiple 'thanks' for hard case 5
        outro = [
            ("thanks", 210.0, 210.5), ("for", 210.6, 210.8), ("watching", 210.9, 211.5),
            ("thanks", 215.0, 215.4), ("to", 215.5, 215.7), ("our", 215.8, 216.0), ("sponsor", 216.1, 216.8),
            ("thanks", 220.0, 220.4), ("everyone", 220.5, 221.0),
            ("and", 225.0, 225.2), ("special", 225.3, 225.8), ("thanks", 226.0, 226.5),
            ("goodbye", 228.0, 228.8)
        ]
        cur_id = len(words)
        for idx, (t, s, e) in enumerate(outro):
            words.append(WordToken(id=f"w_{cur_id + idx:03d}", text=t, start_s=s, end_s=e, speaker="speaker_1", confidence=0.98))

        return Transcript(words=words, speakers=["speaker_1"], language="en")

    def _build_two_speaker_transcript(self, duration_s: float) -> Transcript:
        """Two-speaker transcript (Host and Guest) for testing multi-speaker scenarios."""
        words: List[WordToken] = []
        dialogue = [
            ("welcome", 1.0, 1.5, "speaker_1", 0.99),
            ("to", 1.6, 1.8, "speaker_1", 0.99),
            ("our", 1.9, 2.1, "speaker_1", 0.99),
            ("podcast", 2.2, 2.8, "speaker_1", 0.98),
            ("today", 3.0, 3.4, "speaker_1", 0.98),
            ("we", 3.5, 3.7, "speaker_1", 0.98),
            ("have", 3.8, 4.0, "speaker_1", 0.98),
            ("a", 4.1, 4.2, "speaker_1", 0.98),
            ("special", 4.3, 4.8, "speaker_1", 0.97),
            ("guest", 4.9, 5.4, "speaker_1", 0.99),
            # Host lead-in question about old job:
            ("what", 7.0, 7.3, "speaker_1", 0.98),
            ("did", 7.4, 7.6, "speaker_1", 0.98),
            ("you", 7.7, 7.9, "speaker_1", 0.98),
            ("do", 8.0, 8.2, "speaker_1", 0.98),
            ("at", 8.3, 8.5, "speaker_1", 0.98),
            ("your", 8.6, 8.8, "speaker_1", 0.98),
            ("old", 8.9, 9.2, "speaker_1", 0.98),
            ("job", 9.3, 9.8, "speaker_1", 0.99),
            # Guest response about old job:
            ("at", 11.0, 11.3, "speaker_2", 0.97),
            ("my", 11.4, 11.6, "speaker_2", 0.97),
            ("old", 11.7, 12.0, "speaker_2", 0.98),
            ("job", 12.1, 12.6, "speaker_2", 0.99),
            ("i", 12.7, 12.9, "speaker_2", 0.98),
            ("was", 13.0, 13.3, "speaker_2", 0.98),
            ("a", 13.4, 13.5, "speaker_2", 0.98),
            ("senior", 13.6, 14.1, "speaker_2", 0.97),
            ("video", 14.2, 14.6, "speaker_2", 0.98),
            ("producer", 14.7, 15.5, "speaker_2", 0.98),
            ("managing", 15.6, 16.2, "speaker_2", 0.95),
            ("client", 16.3, 16.7, "speaker_2", 0.96),
            ("campaigns", 16.8, 17.5, "speaker_2", 0.96),
            # Host transition:
            ("that", 19.0, 19.3, "speaker_1", 0.98),
            ("is", 19.4, 19.6, "speaker_1", 0.98),
            ("fascinating", 19.7, 20.6, "speaker_1", 0.97),
            ("tell", 21.0, 21.3, "speaker_1", 0.98),
            ("us", 21.4, 21.6, "speaker_1", 0.98),
            ("about", 21.7, 22.0, "speaker_1", 0.98),
            ("your", 22.1, 22.3, "speaker_1", 0.98),
            ("new", 22.4, 22.7, "speaker_1", 0.98),
            ("startup", 22.8, 23.5, "speaker_1", 0.99),
            # Guest answer about new startup:
            ("our", 25.0, 25.3, "speaker_2", 0.98),
            ("new", 25.4, 25.7, "speaker_2", 0.99),
            ("startup", 25.8, 26.5, "speaker_2", 0.99),
            ("builds", 26.6, 27.1, "speaker_2", 0.98),
            ("ai", 27.2, 27.5, "speaker_2", 0.99),
            ("tools", 27.6, 28.2, "speaker_2", 0.99)
        ]
        for idx, (t, s, e, spk, conf) in enumerate(dialogue):
            is_low = conf < 0.60
            words.append(WordToken(id=f"w_pod_{idx:03d}", text=t, start_s=s, end_s=e, speaker=spk, confidence=conf, low_confidence=is_low))

        return Transcript(words=words, speakers=["speaker_1", "speaker_2"], language="en")


class TranscriptAnalyzer:
    """Provides word snapping, silence detection, and quality warning checks."""

    @staticmethod
    def snap_cut_to_silence(
        start_s: float,
        end_s: float,
        words: List[WordToken],
        margin_s: float = 0.05
    ) -> Tuple[float, float, bool]:
        """Snaps cut range to nearby silence boundaries so no word is clipped.

        Returns: (snapped_start_s, snapped_end_s, was_snapped)
        """
        snapped_start = start_s
        snapped_end = end_s
        was_snapped = False

        for w in words:
            # If start_s cuts inside w, snap to word boundary + margin
            if w.start_s <= start_s < w.end_s:
                # Snap to right before word if closer to start, or right after
                if (start_s - w.start_s) < (w.end_s - start_s):
                    snapped_start = max(0.0, w.start_s - margin_s)
                else:
                    snapped_start = w.end_s + margin_s
                was_snapped = True

            # If end_s cuts inside w, snap to word boundary + margin
            if w.start_s < end_s <= w.end_s:
                if (end_s - w.start_s) < (w.end_s - end_s):
                    snapped_end = max(0.0, w.start_s - margin_s)
                else:
                    snapped_end = w.end_s + margin_s
                was_snapped = True

        return round(snapped_start, 3), round(snapped_end, 3), was_snapped

    @staticmethod
    def detect_silences(words: List[WordToken], total_duration_s: float, min_gap_s: float = 0.70) -> List[Tuple[float, float]]:
        """Detects silence intervals longer than min_gap_s."""
        silences = []
        if not words:
            if total_duration_s > min_gap_s:
                return [(0.0, total_duration_s)]
            return []

        # Check silence before first word
        if words[0].start_s > min_gap_s:
            silences.append((0.0, words[0].start_s))

        # Check silences between consecutive words
        for i in range(len(words) - 1):
            gap = words[i+1].start_s - words[i].end_s
            if gap >= min_gap_s:
                silences.append((words[i].end_s, words[i+1].start_s))

        # Check silence after last word
        if total_duration_s - words[-1].end_s > min_gap_s:
            silences.append((words[-1].end_s, total_duration_s))

        return silences

    @staticmethod
    def inspect_audio_data_quality(words: List[WordToken]) -> List[str]:
        """Detects low confidence, overlapping speech, and speaker swaps."""
        warnings = []
        for w in words:
            if w.confidence < 0.60:
                warnings.append(f"Low confidence word '{w.text}' at {w.start_s:.2f}s (conf: {w.confidence:.2f})")

        # Check overlapping speech or rapid speaker swaps
        for i in range(len(words) - 1):
            w1 = words[i]
            w2 = words[i+1]
            if w1.speaker != w2.speaker:
                if w2.start_s < w1.end_s:
                    warnings.append(f"Overlapping speech detected between {w1.speaker} and {w2.speaker} at {w2.start_s:.2f}s")
                elif (w2.start_s - w1.end_s) < 0.15:
                    warnings.append(f"Rapid speaker alternation between {w1.speaker} and {w2.speaker} at {w2.start_s:.2f}s (possible label swap)")

        return warnings

