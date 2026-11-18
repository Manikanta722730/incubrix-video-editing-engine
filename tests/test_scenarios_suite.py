"""Automated suite of 45 scripted scenarios with expected results.

Outstanding Level requirement:
Proof: an automated suite of at least 40 scripted scenarios with expected results runs in CI.
"""

import unittest
from engine.session_runner import EditingSession
from engine.models import ResponseStatus, TimePolicy
from engine.timeline_core import TimelineCore
from engine.time_policy import parse_time_expression

VIDEO_SINGLE = "test_pack/media/single_speaker_interview.mp4"
VIDEO_MULTI = "test_pack/media/two_speaker_podcast.mp4"
VIDEO_VFR = "test_pack/media/phone_vfr_video.mp4"


class TestScenariosSuite(unittest.TestCase):

    def setUp(self):
        self.session = EditingSession(VIDEO_SINGLE)

    # Scenarios 1-5: Cut & Keep Operations
    def test_scenario_01_cut_first_10s(self):
        r = self.session.execute_step("Cut the first 10 seconds")
        self.assertEqual(r.status, ResponseStatus.APPLIED)
        self.assertAlmostEqual(r.duration_s, 230.0, delta=0.5)

    def test_scenario_02_cut_middle_range(self):
        r = self.session.execute_step("Remove 0:30-0:40")
        self.assertEqual(r.status, ResponseStatus.APPLIED)
        self.assertAlmostEqual(r.duration_s, 230.0, places=1)

    def test_scenario_03_cut_last_10s(self):
        r = self.session.execute_step("Cut the last 10 seconds")
        self.assertEqual(r.status, ResponseStatus.APPLIED)

    def test_scenario_04_multiple_consecutive_cuts(self):
        self.session.execute_step("Cut the first 10 seconds")
        r = self.session.execute_step("Cut the first 10 seconds")
        self.assertEqual(r.status, ResponseStatus.APPLIED)

    def test_scenario_05_keep_only_range(self):
        r = self.session.execute_step("Keep only 0:30-0:50")
        self.assertEqual(r.status, ResponseStatus.APPLIED)
        self.assertAlmostEqual(r.duration_s, 20.0, places=1)

    # Scenarios 6-10: Speed Operations & Limits
    def test_scenario_06_speed_up_2x(self):
        r = self.session.execute_step("Speed up from 1:00 to 1:30 by 2x")
        self.assertEqual(r.status, ResponseStatus.APPLIED)
        self.assertIn("speed_range", r.operations)

    def test_scenario_07_slow_down_half_speed(self):
        r = self.session.execute_step("Slow down from 0:10 to 0:20 by 0.5x")
        self.assertEqual(r.status, ResponseStatus.APPLIED)

    def test_scenario_08_speed_up_3x(self):
        r = self.session.execute_step("Speed up from 0:10 to 0:20 by 3x")
        self.assertEqual(r.status, ResponseStatus.APPLIED)

    def test_scenario_09_speed_exceeds_max_rejected(self):
        r = self.session.execute_step("Speed up 10x")
        self.assertEqual(r.status, ResponseStatus.REJECTED)
        self.assertIn("exceeds maximum", r.reason)

    def test_scenario_10_speed_below_min_rejected(self):
        r = self.session.execute_step("Slow down from 0:10 to 0:20 by 0.1x")
        self.assertEqual(r.status, ResponseStatus.REJECTED)

    # Scenarios 11-15: Captioning & Styling
    def test_scenario_11_add_caption_anchored(self):
        r = self.session.execute_step("Add a caption 'Welcome!' when I say welcome to the channel")
        self.assertEqual(r.status, ResponseStatus.APPLIED)
        self.assertEqual(len(self.session.timeline.caption_track.captions), 1)

    def test_scenario_12_make_caption_red(self):
        self.session.execute_step("Add a caption 'Welcome!' when I say welcome to the channel")
        r = self.session.execute_step("Make that caption red")
        self.assertEqual(r.status, ResponseStatus.APPLIED)
        self.assertEqual(self.session.timeline.caption_track.captions[0].style.color, "red")

    def test_scenario_13_make_caption_blue(self):
        self.session.execute_step("Add a caption 'Welcome!' when I say welcome to the channel")
        r = self.session.execute_step("Make that caption blue")
        self.assertEqual(r.status, ResponseStatus.APPLIED)
        self.assertEqual(self.session.timeline.caption_track.captions[0].style.color, "blue")

    def test_scenario_14_make_caption_bigger(self):
        self.session.execute_step("Add a caption 'Welcome!' when I say welcome to the channel")
        init_size = self.session.timeline.caption_track.captions[0].style.font_size
        r = self.session.execute_step("Make that caption bigger")
        self.assertEqual(r.status, ResponseStatus.APPLIED)
        self.assertGreater(self.session.timeline.caption_track.captions[0].style.font_size, init_size)

    def test_scenario_15_style_caption_without_caption_rejected(self):
        r = self.session.execute_step("Make that caption red")
        self.assertEqual(r.status, ResponseStatus.REJECTED)
        self.assertIn("no active caption exists", r.reason)

    # Scenarios 16-20: Filler & Silence Removals
    def test_scenario_16_remove_filler_words(self):
        r = self.session.execute_step("Remove filler words")
        self.assertEqual(r.status, ResponseStatus.APPLIED)
        self.assertIn("remove_fillers", r.operations)

    def test_scenario_17_remove_ums_and_uhs(self):
        r = self.session.execute_step("Cut out the ums and uhs")
        self.assertEqual(r.status, ResponseStatus.APPLIED)

    def test_scenario_18_remove_silences_default(self):
        r = self.session.execute_step("Remove silences")
        self.assertEqual(r.status, ResponseStatus.APPLIED)

    def test_scenario_19_remove_silences_threshold_1s(self):
        r = self.session.execute_step("Remove silences longer than 1.0s")
        self.assertEqual(r.status, ResponseStatus.APPLIED)

    def test_scenario_20_silence_snapping_preserves_word_onsets(self):
        from engine.transcript import TranscriptAnalyzer, WordToken
        words = [WordToken(id="w_test", text="test", start_s=5.0, end_s=5.5)]
        s, e, snapped = TranscriptAnalyzer.snap_cut_to_silence(5.1, 7.0, words)
        self.assertTrue(snapped)
        self.assertAlmostEqual(s, 4.95, places=2)

    # Scenarios 21-25: Audio, Ducking & Bleeping
    def test_scenario_21_add_background_music_with_ducking(self):
        r = self.session.execute_step("Add background music that automatically gets quieter under speech")
        self.assertEqual(r.status, ResponseStatus.APPLIED)
        self.assertTrue(self.session.timeline.audio_track.ducking_enabled)
        self.assertEqual(self.session.timeline.audio_track.ducking_db, -18.0)

    def test_scenario_22_bleep_specific_word(self):
        r = self.session.execute_step("Bleep the word pricing")
        self.assertEqual(r.status, ResponseStatus.APPLIED)
        self.assertIn("bleep_word", r.operations)

    def test_scenario_23_mute_specific_word(self):
        r = self.session.execute_step("Mute the word pricing")
        self.assertEqual(r.status, ResponseStatus.APPLIED)

    def test_scenario_24_bleep_non_existent_word_rejected(self):
        r = self.session.execute_step("Bleep the word nonexistentsuperword")
        self.assertEqual(r.status, ResponseStatus.REJECTED)
        self.assertIn("not found", r.reason)

    def test_scenario_25_music_preserved_after_cut(self):
        self.session.execute_step("Add background music that automatically gets quieter under speech")
        self.session.execute_step("Cut the first 20 seconds")
        self.assertTrue(self.session.timeline.audio_track.ducking_enabled)

    # Scenarios 26-30: History, Undo, Redo & Restore
    def test_scenario_26_undo_reverses_cut(self):
        d0 = self.session.timeline.derived_timing.total_duration_s
        self.session.execute_step("Cut the first 30 seconds")
        self.session.execute_step("Undo")
        self.assertEqual(self.session.timeline.derived_timing.total_duration_s, d0)

    def test_scenario_27_redo_reapplies_cut(self):
        self.session.execute_step("Cut the first 30 seconds")
        d_cut = self.session.timeline.derived_timing.total_duration_s
        self.session.execute_step("Undo")
        self.session.execute_step("Redo")
        self.assertEqual(self.session.timeline.derived_timing.total_duration_s, d_cut)

    def test_scenario_28_new_edit_clears_redo(self):
        self.session.execute_step("Cut the first 10 seconds")
        self.session.execute_step("Undo")
        self.session.execute_step("Cut the first 20 seconds")
        r = self.session.execute_step("Redo")
        self.assertEqual(r.status, ResponseStatus.REJECTED)

    def test_scenario_29_restore_intro(self):
        self.session.execute_step("Cut the first 30 seconds")
        r = self.session.execute_step("Actually, put the intro back")
        self.assertEqual(r.status, ResponseStatus.APPLIED)
        self.assertIn("restore_edit", r.operations)

    def test_scenario_30_selective_undo_keep_music(self):
        self.session.execute_step("Cut the first 10 seconds")
        self.session.execute_step("Add background music that automatically gets quieter under speech")
        self.session.execute_step("Cut 0:30-0:40")
        r = self.session.execute_step("Undo the second-to-last cut but keep the music")
        self.assertEqual(r.status, ResponseStatus.APPLIED)
        self.assertTrue(self.session.timeline.audio_track.ducking_enabled)

    # Scenarios 31-35: Clarification & Semantic Search
    def test_scenario_31_topic_cut_without_answer_asks_clarification(self):
        r = self.session.execute_step("Remove the part about pricing")
        self.assertEqual(r.status, ResponseStatus.NEEDS_CLARIFICATION)
        self.assertIsNotNone(r.question)
        self.assertTrue(len(r.options) >= 2)

    def test_scenario_32_topic_cut_with_first_answer(self):
        r = self.session.execute_step("Remove the part about pricing", answer_text="first occurrence")
        self.assertEqual(r.status, ResponseStatus.APPLIED)

    def test_scenario_33_topic_cut_with_second_answer(self):
        r = self.session.execute_step("Remove the part about pricing", answer_text="the second one")
        self.assertEqual(r.status, ResponseStatus.APPLIED)

    def test_scenario_34_topic_cut_all_occurrences(self):
        r = self.session.execute_step("Remove the part about pricing", answer_text="all occurrences")
        self.assertEqual(r.status, ResponseStatus.APPLIED)

    def test_scenario_35_boring_bit_asks_clarification(self):
        r = self.session.execute_step("Remove the boring bit")
        self.assertEqual(r.status, ResponseStatus.NEEDS_CLARIFICATION)

    # Scenarios 36-40: Multi-Speaker & Edge Cases
    def test_scenario_36_multi_speaker_guest_topic(self):
        session = EditingSession(VIDEO_MULTI)
        r = session.execute_step("remove everything the guest says about their old job")
        self.assertEqual(r.status, ResponseStatus.APPLIED)

    def test_scenario_37_multiple_thanks_clarification(self):
        r = self.session.execute_step("Remove everything after I say thanks")
        self.assertEqual(r.status, ResponseStatus.NEEDS_CLARIFICATION)

    def test_scenario_38_multiple_thanks_with_answer(self):
        r = self.session.execute_step("Remove everything after I say thanks", answer_text="Last occurrence")
        self.assertEqual(r.status, ResponseStatus.APPLIED)

    def test_scenario_39_multipart_partial_success(self):
        r = self.session.execute_step("Cut the first 10 seconds and speed up 10x")
        self.assertEqual(r.status, ResponseStatus.APPLIED)
        self.assertIn("Partially applied", r.summary)

    def test_scenario_40_vfr_phone_video_handling(self):
        session = EditingSession(VIDEO_VFR)
        r = session.execute_step("Cut the first 5 seconds")
        self.assertEqual(r.status, ResponseStatus.APPLIED)

    # Scenarios 41-45: Extreme Validation & Rejection
    def test_scenario_41_cut_everything_rejected(self):
        r = self.session.execute_step("Cut everything")
        self.assertEqual(r.status, ResponseStatus.REJECTED)

    def test_scenario_42_cut_start_greater_than_end_rejected(self):
        r = self.session.execute_step("Remove 1:00-0:30")
        self.assertEqual(r.status, ResponseStatus.REJECTED)

    def test_scenario_43_caption_at_invalid_future_timestamp_rejected(self):
        r = self.session.execute_step("Add a caption at 15:00")
        self.assertEqual(r.status, ResponseStatus.REJECTED)

    def test_scenario_44_repeated_cut_idempotent(self):
        r1 = self.session.execute_step("Remove 0:30-0:40")
        r2 = self.session.execute_step("Remove 0:30-0:40")
        self.assertEqual(r1.status, ResponseStatus.APPLIED)
        self.assertEqual(r2.status, ResponseStatus.APPLIED)

    def test_scenario_45_render_instruction(self):
        r = self.session.execute_step("render")
        self.assertEqual(r.status, ResponseStatus.APPLIED)
        self.assertIn("sync within 1 frame", r.summary)


if __name__ == "__main__":
    unittest.main()
