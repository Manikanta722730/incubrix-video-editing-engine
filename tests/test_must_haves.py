"""Test suite for IncuBrix Must-Haves (1-8).

Must-haves:
1. Never damage the original.
2. Edits stick to content.
3. Three-way answers (Applied, Needs clarification, Rejected).
4. Predictable (identical timeline_hash across 3 runs).
5. Render matches timeline within 1 frame.
6. All operations work including undo/redo and selective restore.
7. Clear time policy stated in answer.
8. Integration Standard followed, session runner works.
"""

import os
import hashlib
import unittest
from engine.session_runner import EditingSession, run_session_file
from engine.models import ResponseStatus, TimePolicy
from engine.renderer import TimelineRenderer
from engine.timeline_core import TimelineCore

VIDEO_PATH = "test_pack/media/single_speaker_interview.mp4"


class TestMustHaves(unittest.TestCase):

    def test_must_have_1_never_damage_original(self):
        """Must-have 1: Source file hash is unchanged before and after session."""
        self.assertTrue(os.path.exists(VIDEO_PATH), f"Media file {VIDEO_PATH} missing")
        with open(VIDEO_PATH, "rb") as f:
            hash_before = hashlib.sha256(f.read()).hexdigest()

        session = EditingSession(VIDEO_PATH)
        session.execute_step("Add a caption 'Welcome!' when I say welcome to the channel")
        session.execute_step("Cut the first 30 seconds")
        session.execute_step("Speed up from 1:00 to 1:30 by 2x")
        session.execute_step("Undo")
        session.execute_step("Remove filler words")

        with open(VIDEO_PATH, "rb") as f:
            hash_after = hashlib.sha256(f.read()).hexdigest()

        self.assertEqual(hash_before, hash_after, "Must-have 1 Failed: Source file was mutated!")
        self.assertEqual(session.source_hash, hash_after)

    def test_must_have_2_edits_stick_to_content(self):
        """Must-have 2: Captions stick to content, not clock time."""
        session = EditingSession(VIDEO_PATH)
        r1 = session.execute_step("Add a caption 'Welcome!' when I say welcome to the channel")
        self.assertEqual(r1.status, ResponseStatus.APPLIED)
        caption = session.timeline.caption_track.captions[0]
        self.assertEqual(len(caption.anchor_word_ids), 4)

        p1 = TimelineCore.calculate_caption_playout(session.timeline, caption)
        self.assertIsNotNone(p1)
        self.assertTrue(41.5 <= p1[0] <= 42.5)

        r2 = session.execute_step("Cut the first 30 seconds")
        self.assertEqual(r2.status, ResponseStatus.APPLIED)

        p2 = TimelineCore.calculate_caption_playout(session.timeline, caption)
        self.assertIsNotNone(p2)
        # After cutting 30s, caption must play at 12.0s
        self.assertTrue(11.5 <= p2[0] <= 12.5, f"Caption drifted! Got {p2[0]}s")

    def test_must_have_3_three_way_answers(self):
        """Must-have 3: Returns Applied, Needs clarification, or Rejected."""
        session = EditingSession(VIDEO_PATH)

        r_applied = session.execute_step("Cut the first 10 seconds")
        self.assertEqual(r_applied.status, ResponseStatus.APPLIED)
        self.assertTrue(len(r_applied.operations) > 0)

        r_clarify = session.execute_step("Remove the part about pricing")
        self.assertEqual(r_clarify.status, ResponseStatus.NEEDS_CLARIFICATION)
        self.assertIsNotNone(r_clarify.question)

        r_rejected = session.execute_step("Add a caption at 10:00")
        self.assertEqual(r_rejected.status, ResponseStatus.REJECTED)
        self.assertIsNotNone(r_rejected.reason)

    def test_must_have_4_predictability(self):
        """Must-have 4: Three independent runs produce 100% identical timeline_hash."""
        hashes = []
        for _ in range(3):
            session = EditingSession(VIDEO_PATH)
            session.execute_step("Add a caption 'Welcome!' when I say welcome to the channel")
            session.execute_step("Cut the first 30 seconds")
            session.execute_step("Speed up from 1:00 to 1:30 by 2x")
            session.execute_step("Make that caption red")
            hashes.append(session.timeline.derived_timing.timeline_hash)

        self.assertEqual(hashes[0], hashes[1])
        self.assertEqual(hashes[1], hashes[2])

    def test_must_have_5_render_matches_timeline(self):
        """Must-have 5: Audio and video in sync within 1 frame, length matches timeline within 1 frame."""
        podcast_media = "test_pack/media/two_speaker_podcast.mp4"
        session = EditingSession(podcast_media)
        session.execute_step("Cut the first 5 seconds")
        session.execute_step("Speed up from 0:10 to 0:15 by 2x")

        out_file = "test_pack/outputs/test_render_accuracy.mp4"
        renderer = TimelineRenderer()
        res = renderer.render(session.timeline, out_file)

        self.assertTrue(res["in_sync_within_1_frame"])
        self.assertLessEqual(res["frame_diff"], 1.0)

    def test_must_have_6_all_operations_and_undo_redo(self):
        """Must-have 6: All operations work, undo/redo stack behaves correctly."""
        session = EditingSession(VIDEO_PATH)
        session.execute_step("Cut the first 20 seconds")
        h1 = session.timeline.derived_timing.timeline_hash

        session.execute_step("Add background music that automatically gets quieter under speech")
        h2 = session.timeline.derived_timing.timeline_hash
        self.assertNotEqual(h1, h2)

        r_undo = session.execute_step("Undo")
        self.assertEqual(r_undo.status, ResponseStatus.APPLIED)
        self.assertEqual(session.timeline.derived_timing.timeline_hash, h1)

        session.execute_step("Speed up from 1:00 to 1:30 by 2x")
        r_redo = session.execute_step("Redo")
        self.assertEqual(r_redo.status, ResponseStatus.REJECTED)

    def test_must_have_7_clear_time_policy(self):
        """Must-have 7: Time policy is stated in answer everywhere."""
        session = EditingSession(VIDEO_PATH, time_policy=TimePolicy.ORIGINAL_MEDIA_TIME)
        session.execute_step("Cut the first 30 seconds")
        r = session.execute_step("Speed up from 1:00 to 1:30 by 2x")

        self.assertEqual(r.status, ResponseStatus.APPLIED)
        self.assertEqual(r.time_policy, "original_media_time")
        self.assertIn("Using policy 'original_media_time'", r.summary)

    def test_must_have_8_session_runner(self):
        """Must-have 8: Session runner tool parses YAML and generates valid results.json."""
        res = run_session_file("test_pack/sessions/session_01_worked_example.yaml", "test_pack/outputs/mh8_test")
        self.assertTrue(res["untouched_verified"])
        self.assertEqual(res["total_steps"], 8)
        self.assertTrue(os.path.exists("test_pack/outputs/mh8_test/results.json"))
        self.assertTrue(os.path.exists("test_pack/outputs/mh8_test/timeline.json"))


if __name__ == "__main__":
    unittest.main()
