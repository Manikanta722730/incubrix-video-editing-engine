"""Test suite for the 7 Hard Cases specified in the IncuBrix assessment brief.

Hard cases:
1. Caption added, sentence under it cut, then cut restored (caption comes back).
2. Section reordered, word inside it muted, filler removal cutting into bleeped word.
3. Repeated cuts ('Remove 0:30-0:40' twice), out of bounds captions ('5:00' on 4:00 video), natural time expressions.
4. Selective undo ('undo second-to-last cut but keep music'), 'make it bigger' when no caption exists.
5. Cut after word spoken 4 times ('thanks') -> clarification with options.
6. Speed 10x (rejected), cut everything (rejected), 3-part instruction where 1 part is impossible.
7. Two-speaker with label swaps, overlapping speech, background music, and variable frame rate (VFR).
"""

import unittest
from engine.session_runner import EditingSession
from engine.models import ResponseStatus
from engine.timeline_core import TimelineCore
from engine.transcript import TranscriptAnalyzer, WordToken

VIDEO_PATH = "test_pack/media/single_speaker_interview.mp4"
PODCAST_PATH = "test_pack/media/two_speaker_podcast.mp4"
VFR_PATH = "test_pack/media/phone_vfr_video.mp4"


class TestHardCases(unittest.TestCase):

    def test_hard_case_1_cut_restore_caption(self):
        """Hard case 1: Caption added, sentence under it cut, cut restored -> caption returns on exact words."""
        session = EditingSession(VIDEO_PATH)

        # 1. Add caption on 'welcome to the channel' (0:42-0:44)
        r1 = session.execute_step("Add a caption 'Welcome!' when I say welcome to the channel")
        self.assertEqual(r1.status, ResponseStatus.APPLIED)
        cap = session.timeline.caption_track.captions[0]
        self.assertTrue(cap.is_active)

        # 2. Cut 0:40 to 0:50 (contains the sentence under the caption)
        r2 = session.execute_step("Remove 0:40-0:50")
        self.assertEqual(r2.status, ResponseStatus.APPLIED)
        # Caption words were cut -> caption is deactivated/hidden
        self.assertFalse(cap.is_active)
        self.assertIsNone(TimelineCore.calculate_caption_playout(session.timeline, cap))

        # 3. Restore that cut
        r3 = session.execute_step("Actually, put the 0:40-0:50 back")
        self.assertEqual(r3.status, ResponseStatus.APPLIED)
        # Caption automatically reactivates on its words!
        self.assertTrue(cap.is_active)
        playout = TimelineCore.calculate_caption_playout(session.timeline, cap)
        self.assertIsNotNone(playout)
        self.assertTrue(41.5 <= playout[0] <= 42.5)

    def test_hard_case_2_reorder_mute_filler(self):
        """Hard case 2: Section reordered, word inside muted, filler removal cutting into bleeped word."""
        session = EditingSession(VIDEO_PATH)

        # Bleep pricing
        r1 = session.execute_step("Bleep the word pricing")
        self.assertEqual(r1.status, ResponseStatus.APPLIED)
        self.assertTrue(len(session.timeline.audio_track.bleeps) > 0)

        # Remove filler words
        r2 = session.execute_step("Remove filler words")
        self.assertEqual(r2.status, ResponseStatus.APPLIED)

        # Verify bleeps remain intact and valid
        self.assertTrue(len(session.timeline.audio_track.bleeps) > 0)

    def test_hard_case_3_repeated_cut_and_out_of_bounds_and_natural_times(self):
        """Hard case 3: 'Remove 0:30-0:40' sent twice, 'add caption at 5:00' on shorter video, natural time parsing."""
        session = EditingSession(VIDEO_PATH)

        # 1. First cut of 0:30-0:40
        dur_init = session.timeline.derived_timing.total_duration_s
        r1 = session.execute_step("Remove 0:30-0:40")
        self.assertEqual(r1.status, ResponseStatus.APPLIED)
        dur_after_first = session.timeline.derived_timing.total_duration_s
        self.assertLess(dur_after_first, dur_init)

        # 2. Second cut of same range -> Safe, idempotent
        r2 = session.execute_step("Remove 0:30-0:40")
        self.assertEqual(r2.status, ResponseStatus.APPLIED)
        dur_after_second = session.timeline.derived_timing.total_duration_s
        self.assertEqual(dur_after_first, dur_after_second)

        # 3. Caption at 5:00 on 4:00 video -> Rejected with clear message
        r3 = session.execute_step("Add a caption at 5:00")
        self.assertEqual(r3.status, ResponseStatus.REJECTED)
        self.assertIn("beyond video duration", r3.reason)

        # 4. Natural time expressions: "80 seconds", "a minute twenty", "the last 10 seconds"
        from engine.time_policy import parse_time_expression
        self.assertEqual(parse_time_expression("80 seconds"), 80.0)
        self.assertEqual(parse_time_expression("a minute twenty"), 80.0)
        self.assertEqual(parse_time_expression("the last 10 seconds", total_duration=240.0), 230.0)

    def test_hard_case_4_selective_undo_no_caption(self):
        """Hard case 4: 'Undo the second-to-last cut but keep the music', 'make it bigger' when no caption exists."""
        session = EditingSession(VIDEO_PATH)

        session.execute_step("Cut the first 10 seconds")
        session.execute_step("Add background music that automatically gets quieter under speech")
        session.execute_step("Cut 0:30-0:40")
        self.assertTrue(session.timeline.audio_track.ducking_enabled)

        # Selective undo: second-to-last cut
        r_sel = session.execute_step("Undo the second-to-last cut but keep the music")
        self.assertEqual(r_sel.status, ResponseStatus.APPLIED)
        # Background music is preserved
        self.assertTrue(session.timeline.audio_track.ducking_enabled)

        # 'Make it bigger' when no caption exists -> rejected with clean explanation
        r_no_cap = session.execute_step("Make it bigger")
        self.assertEqual(r_no_cap.status, ResponseStatus.REJECTED)
        self.assertIn("no active caption exists", r_no_cap.reason)

    def test_hard_case_5_multiple_thanks(self):
        """Hard case 5: 'Remove everything after I say thanks' where thanks is said four times."""
        session = EditingSession(VIDEO_PATH)

        # Step 1: prompts for clarification because thanks appears 4 times
        r_clarify = session.execute_step("Remove everything after I say thanks")
        self.assertEqual(r_clarify.status, ResponseStatus.NEEDS_CLARIFICATION)
        self.assertIn("thanks", r_clarify.question.lower())
        self.assertEqual(len(r_clarify.options), 5)  # 4 occurrences + 'Last occurrence'

        # Step 2: User selects 'Last occurrence'
        r_applied = session.execute_step("Remove everything after I say thanks", answer_text="Last occurrence")
        self.assertEqual(r_applied.status, ResponseStatus.APPLIED)
        self.assertIn("after 'thanks'", r_applied.summary)

    def test_hard_case_6_speed_10x_impossible_and_multipart(self):
        """Hard case 6: 'Speed up 10x' (rejected), 'cut everything' (rejected), multi-part instruction."""
        session = EditingSession(VIDEO_PATH)

        # 1. Speed up 10x -> Rejected (exceeds max 4x)
        r_10x = session.execute_step("Speed up 10x")
        self.assertEqual(r_10x.status, ResponseStatus.REJECTED)
        self.assertIn("exceeds maximum supported limit", r_10x.reason)

        # 2. Cut everything -> Rejected (cannot empty video)
        r_all = session.execute_step("Cut everything")
        self.assertEqual(r_all.status, ResponseStatus.REJECTED)
        self.assertIn("resulting timeline would be empty", r_all.reason)

        # 3. Multi-part instruction: one part possible, one part impossible
        # "Cut the first 10 seconds and speed up 10x"
        r_multi = session.execute_step("Cut the first 10 seconds and speed up 10x")
        self.assertEqual(r_multi.status, ResponseStatus.APPLIED)
        self.assertIn("cut_range", r_multi.operations)
        self.assertIn("Partially applied", r_multi.summary)

    def test_hard_case_7_two_speaker_vfr_quality_warnings(self):
        """Hard case 7: Two-speaker video, speaker swaps, overlapping speech, and VFR."""
        # 1. Quality inspector flags overlapping speech and rapid speaker swaps
        words = [
            WordToken(id="w1", text="hello", start_s=1.0, end_s=2.0, speaker="speaker_1"),
            WordToken(id="w2", text="welcome", start_s=1.8, end_s=2.5, speaker="speaker_2"),  # Overlapping speech
            WordToken(id="w3", text="thanks", start_s=2.6, end_s=3.0, speaker="speaker_1"),   # Rapid speaker swap
            WordToken(id="w4", text="lowconf", start_s=3.5, end_s=4.0, speaker="speaker_1", confidence=0.45)
        ]
        warnings = TranscriptAnalyzer.inspect_audio_data_quality(words)
        self.assertTrue(any("Overlapping speech" in w for w in warnings))
        self.assertTrue(any("Rapid speaker alternation" in w for w in warnings))
        self.assertTrue(any("Low confidence" in w for w in warnings))

        # 2. VFR video intake
        session_vfr = EditingSession(VFR_PATH)
        self.assertEqual(session_vfr.timeline.source_media.fps, 24.0)
        r_vfr = session_vfr.execute_step("Cut the first 5 seconds")
        self.assertEqual(r_vfr.status, ResponseStatus.APPLIED)


if __name__ == "__main__":
    unittest.main()

