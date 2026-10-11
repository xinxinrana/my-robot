"""One monotonic presentation clock for live TCP preview frames."""

import math

import numpy as np


class PresentationClock:
    """Return absolute display deadlines, skipping missed slots without bursts."""

    def __init__(self, fps, start_time):
        self.period = 1.0 / max(0.5, float(fps))
        self.next_time = float(start_time)
        self.skipped = 0

    def next_deadline(self, now):
        now = float(now)
        if now > self.next_time:
            missed = math.ceil((now - self.next_time) / self.period)
            self.next_time += missed * self.period
            self.skipped += missed
        deadline = self.next_time
        self.next_time += self.period
        return deadline


class DisplayPose:
    """Causal smoothing for display only; solver results remain untouched."""

    def __init__(self, response_seconds=0.12):
        self.response_seconds = max(0.0, float(response_seconds))
        self.value = None

    def step(self, target, elapsed_seconds):
        target = np.asarray(target, dtype=np.float64)
        if target.ndim != 1 or not np.isfinite(target).all():
            raise ValueError("display pose must be a finite vector")
        if self.value is None or self.value.shape != target.shape:
            self.value = target.copy()
            return self.value.copy()
        dt = max(0.0, float(elapsed_seconds))
        alpha = 1.0 if self.response_seconds == 0.0 else -math.expm1(-dt / self.response_seconds)
        result = self.value + alpha * (target - self.value)
        if target.size >= 7:
            start = self.value[3:7]
            end = target[3:7]
            if np.dot(start, end) < 0.0:
                end = -end
            quat = start + alpha * (end - start)
            norm = np.linalg.norm(quat)
            result[3:7] = quat / norm if norm > 1e-12 else end
        self.value = result
        return result.copy()
