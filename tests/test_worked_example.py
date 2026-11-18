"""Test suite for the exact 8-step worked example specified in the assessment brief.

User types:
1. Add a caption 'Welcome!' when I say welcome to the channel -> Applied. Attached to 4 words (orig 0:42-0:44).
2. Cut the first 30 seconds -> Applied. Video 30s shorter. Caption plays at 0:12-0:14.
3. Remove the part about pricing -> Clarification: which one or all? User: the second one -> Applied.
4. Speed up from 1:00 to 1:30 by 2x -> Applied, stating time policy used.
5. Actually, put the intro back -> Applied. First 30s return; caption back at 0:42; pricing cut and speed stay.
6. Undo -> Reverses step 5 only. Intro cut again.
7. Make that caption red -> Applied to the Welcome! caption, the only one that exists.
8. Render -> Audio and video in sync within 1 frame, length matches timeline.
"""

import unittest
from engine.session_runner import EditingSession
from engine.models import ResponseStatus
from engine.timeline_core import TimelineCore
from engine.renderer import TimelineRenderer

VIDEO_PATH = "test_pack/media/single_speaker_interview.mp4"


class TestWorkedExample(unittest.TestCase):

    def test_reproduce_exact_8_step_worked_example(self):
        session = EditingSession(VIDEO_PATH)

        # Step 1
        r1 = session.execute_step("Add a caption 'Welcome!' when I say welcome to the channel")
        self.assertEqual(r1.status, ResponseStatus.APPLIED)
        self.assertEqual(len(session.timeline.caption_track.captions), 1)
        cap = session.timeline.caption_track.captions[0]
        self.assertEqual(cap.text, "Welcome!")
        p1 = TimelineCore.calculate_caption_playout(session.timeline, cap)
        self.assertIsNotNone(p1)
        self.assertTrue(41.5 <= p1[0] <= 42.5)

        # Step 2
        r2 = session.execute_step("Cut the first 30 seconds")
        self.assertEqual(r2.status, ResponseStatus.APPLIED)
        p2 = TimelineCore.calculate_caption_playout(session.timeline, cap)
        self.assertIsNotNone(p2)
        self.assertTrue(11.5 <= p2[0] <= 12.5)

        # Step 3
        # First call without answer prompts for clarification
        r3_clarify = session.execute_step("Remove the part about pricing")
        self.assertEqual(r3_clarify.status, ResponseStatus.NEEDS_CLARIFICATION)
        self.assertIn("pricing", r3_clarify.question.lower())

        # Second call with answer 'the second one' applies
        r3_applied = session.execute_step("Remove the part about pricing", answer_text="the second one")
        self.assertEqual(r3_applied.status, ResponseStatus.APPLIED)

        # Step 4
        r4 = session.execute_step("Speed up from 1:00 to 1:30 by 2x")
        self.assertEqual(r4.status, ResponseStatus.APPLIED)
        self.assertIsNotNone(r4.time_policy)
        self.assertIn("Using policy 'original_media_time'", r4.summary)

        # Step 5
        r5 = session.execute_step("Actually, put the intro back")
        self.assertEqual(r5.status, ResponseStatus.APPLIED)
        p5 = TimelineCore.calculate_caption_playout(session.timeline, cap)
        self.assertIsNotNone(p5)
        self.assertTrue(41.5 <= p5[0] <= 42.5)  # Caption returned to original position 0:42

        # Step 6
        r6 = session.execute_step("Undo")
        self.assertEqual(r6.status, ResponseStatus.APPLIED)
        # Intro is cut again, caption returns to 0:12
        p6 = TimelineCore.calculate_caption_playout(session.timeline, cap)
        self.assertIsNotNone(p6)
        self.assertTrue(11.5 <= p6[0] <= 12.5)

        # Step 7
        r7 = session.execute_step("Make that caption red")
        self.assertEqual(r7.status, ResponseStatus.APPLIED)
        active_cap = session.timeline.caption_track.captions[0]
        self.assertEqual(active_cap.style.color, "red")

        # Step 8
        r8 = session.execute_step("render")
        self.assertEqual(r8.status, ResponseStatus.APPLIED)
        self.assertIn("sync within 1 frame", r8.summary)


if __name__ == "__main__":
    unittest.main()
