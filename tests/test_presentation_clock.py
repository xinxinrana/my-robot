import unittest

import numpy as np

from scripts.presentation_clock import DisplayPose, PresentationClock


class PresentationClockTests(unittest.TestCase):
    def test_skips_missed_slots_instead_of_catching_up_in_a_burst(self):
        clock = PresentationClock(fps=10, start_time=1.0)
        self.assertAlmostEqual(clock.next_deadline(1.0), 1.0)
        self.assertAlmostEqual(clock.next_deadline(1.31), 1.4)
        self.assertEqual(clock.skipped, 3)
        self.assertAlmostEqual(clock.next_deadline(1.41), 1.5)

    def test_display_pose_eases_without_mutating_solver_pose(self):
        smoother = DisplayPose(response_seconds=0.1)
        original = np.array([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0])
        target = original.copy()
        target[0] = 1.0
        smoother.step(original, 0.0)
        first = smoother.step(target, 0.05)
        second = smoother.step(target, 0.05)
        self.assertTrue(0.0 < first[0] < second[0] < 1.0)
        self.assertEqual(target[0], 1.0)

    def test_shortest_arc_avoids_quaternion_sign_flip(self):
        smoother = DisplayPose(response_seconds=0.1)
        original = np.array([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0])
        target = original.copy()
        target[3] = -1.0
        smoother.step(original, 0.0)
        np.testing.assert_allclose(smoother.step(target, 0.1)[3:7], original[3:7])


if __name__ == "__main__":
    unittest.main()
