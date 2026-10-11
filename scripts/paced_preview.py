"""Small, causal pose smoother for the live TCP robot preview.

This changes display poses only. Inference results and exported joint rows retain
their original timestamps and values.
"""

import math

import numpy as np


class PoseEaser:
    def __init__(self, response_seconds=0.16):
        self.response_seconds = max(0.0, float(response_seconds))
        self._display = None

    def step(self, target, elapsed_seconds):
        target = np.asarray(target, dtype=np.float64)
        if target.ndim != 1 or not np.isfinite(target).all():
            raise ValueError("preview pose must be a finite vector")
        if self._display is None or self._display.shape != target.shape:
            self._display = target.copy()
            return self._display.copy()

        dt = max(0.0, float(elapsed_seconds))
        alpha = 1.0 if self.response_seconds == 0.0 else -math.expm1(-dt / self.response_seconds)
        display = self._display + alpha * (target - self._display)

        # MuJoCo free-root qpos stores its rotation as a wxyz quaternion.
        # Interpolate along the short arc and normalize; component-wise linear
        # interpolation can make a rotation jump when q and -q encode the same pose.
        if target.size >= 7:
            start = self._display[3:7]
            end = target[3:7]
            if np.dot(start, end) < 0.0:
                end = -end
            quat = start + alpha * (end - start)
            norm = np.linalg.norm(quat)
            display[3:7] = quat / norm if norm > 1e-12 else end

        self._display = display
        return display.copy()
