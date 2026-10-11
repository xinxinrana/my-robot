import unittest

import numpy as np

from scripts.paced_preview import PoseEaser


class PoseEaserTests(unittest.TestCase):
    def test_spreads_a_new_target_across_display_ticks(self):
        smoother = PoseEaser(response_seconds=0.1)
        initial = np.array([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0])
        target = initial.copy()
        target[0] = 1.0
        target[7] = 2.0
        smoother.step(initial, 0.0)
        first = smoother.step(target, 0.05)
        second = smoother.step(target, 0.05)
        self.assertTrue(0.0 < first[0] < second[0] < 1.0)
        self.assertTrue(0.0 < first[7] < second[7] < 2.0)

    def test_equivalent_opposite_quaternions_do_not_flip(self):
        smoother = PoseEaser(response_seconds=0.1)
        initial = np.array([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0])
        target = initial.copy()
        target[3] = -1.0
        smoother.step(initial, 0.0)
        pose = smoother.step(target, 0.1)
        np.testing.assert_allclose(pose[3:7], initial[3:7])

    def test_zero_response_tracks_target_immediately(self):
        smoother = PoseEaser(response_seconds=0.0)
        smoother.step(np.array([0.0]), 0.0)
        np.testing.assert_allclose(smoother.step(np.array([3.0]), 0.01), [3.0])


if __name__ == "__main__":
    unittest.main()
