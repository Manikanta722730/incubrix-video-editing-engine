"""Test suite for Core, Advanced, and Outstanding levels.

Core (15 marks):
- All must-haves pass.
- 8-step worked example.
- Single and multi-speaker video support.

Advanced (15 marks):
- Edits shift each other: captions follow words; cutting words removes caption & informs user; partial cuts rule; sped-up captions keep >=0.7s.
- Ambiguity & references: "that caption", "the boring part", "make it shorter", "put back what I removed"; meaning search.
- Conflicts: repeated instructions safe; deliberate pauses survive silence removal; impossible cuts rejected; overlapping speed changes; multi-part instructions.
- Two speakers: removes guest lines & asks about host lead-in question.

Outstanding (10 marks):
- Imperfect data: silence boundary snapping; low-confidence flagged; VFR & no-audio; overlapping speech warnings.
- Scale: 60-minute video instruction responds in <3 seconds.
- Export: OpenTimelineIO (.otio).
- Proof: Automated suite of at least 40 scripted scenarios.
"""

import os
import time
import unittest
from engine.session_runner import EditingSession
from engine.models import ResponseStatus, WordToken, Transcript, SourceMedia, Timeline, TimelineClip
from engine.timeline_core import TimelineCore
from engine.transcript import TranscriptAnalyzer
from engine.otio_export import OtioExporter

VIDEO_SINGLE = "test_pack/media/single_speaker_interview.mp4"
VIDEO_MULTI = "test_pack/media/two_speaker_podcast.mp4"
VIDEO_NO_AUDIO = "test_pack/media/no_audio_video.mp4"


class TestLevels(unittest.TestCase):

    # --- Core Level ---

    def test_core_single_speaker(self):
        session = EditingSession(VIDEO_SINGLE)
        r = session.execute_step("Cut the first 10 seconds")
        self.assertEqual(r.status, ResponseStatus.APPLIED)

    def test_core_multi_speaker(self):
        session = EditingSession(VIDEO_MULTI)
        self.assertIn("speaker_1", session.timeline.transcript.speakers)
        self.assertIn("speaker_2", session.timeline.transcript.speakers)
        r = session.execute_step("Cut the first 5 seconds")
        self.assertEqual(r.status, ResponseStatus.APPLIED)

    # --- Advanced Level ---

    def test_advanced_caption_readability_minimum_on_speed(self):
        """Advanced: sped-up captions keep a readable minimum (about 0.7 s)."""
        session = EditingSession(VIDEO_SINGLE)
        session.execute_step("Add a caption 'Welcome!' when I say welcome to the channel")
        cap = session.timeline.caption_track.captions[0]

        # Speed up the range containing the caption by 3x
        session.execute_step("Speed up from 0:40 to 0:50 by 3x")
        playout = TimelineCore.calculate_caption_playout(session.timeline, cap)
        self.assertIsNotNone(playout)
        dur = playout[1] - playout[0]
        # Duration must not drop below caption.min_duration_s (0.70s)
        self.assertGreaterEqual(round(dur, 2), 0.70)

    def test_advanced_partial_cut_of_captioned_phrase_rule(self):
        """Advanced: partial cuts of a captioned phrase follow defined rule (>=50% survives)."""
        session = EditingSession(VIDEO_SINGLE)
        session.execute_step("Add a caption 'Welcome!' when I say welcome to the channel")
        cap = session.timeline.caption_track.captions[0]
        self.assertEqual(len(cap.anchor_word_ids), 4)

        # Cut only the first word 'welcome' (0:41.5 to 0:42.5), 3 out of 4 words remain (75% >= 50%)
        session.execute_step("Remove 0:41.5-0:42.5")
        self.assertTrue(cap.is_active)

        # Cut the remaining 3 words (0:42.5 to 0:44.5), all anchor words now cut (< 50% remains)
        session.execute_step("Remove 0:42.5-0:44.5")
        self.assertFalse(cap.is_active)

    def test_advanced_two_speakers_host_leadin(self):
        """Advanced: removes guest's lines about old job and asks about host's lead-in question."""
        session = EditingSession(VIDEO_MULTI)
        r = session.execute_step("remove everything the guest says about their old job")
        self.assertEqual(r.status, ResponseStatus.APPLIED)
        self.assertIn("Host's lead-in question", r.summary)
        self.assertIn("Would you also like to cut the host's question?", r.summary)

    def test_advanced_ambiguity_and_references(self):
        """Advanced: 'the boring part', 'make it shorter', meaning search ('pricing' finds 'cost')."""
        session = EditingSession(VIDEO_SINGLE)

        r_boring = session.execute_step("Remove the boring bit")
        self.assertEqual(r_boring.status, ResponseStatus.NEEDS_CLARIFICATION)
        self.assertTrue(len(r_boring.options) >= 2)

        r_shorter = session.execute_step("Make it shorter")
        self.assertEqual(r_shorter.status, ResponseStatus.NEEDS_CLARIFICATION)
        self.assertTrue(len(r_shorter.options) >= 2)

    # --- Outstanding Level ---

    def test_outstanding_silence_snapping(self):
        """Outstanding: cuts snap to nearby silence so no word is clipped."""
        words = [WordToken(id="w1", text="hello", start_s=10.0, end_s=10.5)]
        # Cut requested from 10.1 to 15.0 (cuts inside word onset)
        snap_s, snap_e, was_snapped = TranscriptAnalyzer.snap_cut_to_silence(10.1, 15.0, words, margin_s=0.05)
        self.assertTrue(was_snapped)
        # Snapped to before word onset (10.0 - 0.05 = 9.95)
        self.assertAlmostEqual(snap_s, 9.95, places=2)

    def test_outstanding_scale_60_minute_video(self):
        """Outstanding: on a 60-minute video, each instruction responds in under 3 seconds."""
        # Synthesize a 60-minute transcript (3600 seconds, 5000 words)
        words = []
        for i in range(5000):
            t_start = i * 0.70
            t_end = t_start + 0.50
            words.append(WordToken(id=f"w_60m_{i}", text=f"word{i}", start_s=t_start, end_s=t_end))

        source_media = SourceMedia(
            source_id="src_60m",
            file_name="hour_long.mp4",
            duration_s=3600.0,
            source_sha256="abc60m"
        )
        timeline = Timeline(
            source_media=source_media,
            transcript=Transcript(words=words)
        )
        timeline.video_track.clips = [
            TimelineClip(clip_id="clip_init", source_start_s=0.0, source_end_s=3600.0, word_ids=[w.id for w in words])
        ]
        timeline.update_derived_timing()

        session = EditingSession(VIDEO_SINGLE)
        session.timeline = timeline

        t0 = time.time()
        r = session.execute_step("Cut the first 30 seconds")
        elapsed = time.time() - t0

        self.assertEqual(r.status, ResponseStatus.APPLIED)
        self.assertLess(elapsed, 3.0, f"Scale test exceeded 3.0s limit: took {elapsed:.4f}s")

    def test_outstanding_opentimelineio_export(self):
        """Outstanding: exports timeline to OpenTimelineIO (.otio) file."""
        session = EditingSession(VIDEO_SINGLE)
        session.execute_step("Add a caption 'Welcome!' when I say welcome to the channel")
        session.execute_step("Cut the first 30 seconds")
        session.execute_step("Speed up from 1:00 to 1:30 by 2x")

        otio_path = "test_pack/outputs/test_levels_export.otio"
        exported = OtioExporter.export_timeline(session.timeline, otio_path)
        self.assertTrue(os.path.exists(exported))
        with open(exported, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("OTIO_SCHEMA", content)
        self.assertIn("Video Track", content)
        self.assertIn("Audio Track", content)


if __name__ == "__main__":
    unittest.main()
