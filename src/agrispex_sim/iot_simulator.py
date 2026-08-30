"""Calibrated, deterministic synthetic IoT generator (numpy-only, pandas-free).

Defaults are calibrated to the real FARM5.0 fused time series we collected
(node1/node2, 947 hourly rows):

    temperature : diurnal ~9.4 -> 22.0 C, mean ~14.8, range 2-32.4
    humidity    : diurnal ~88 -> 55 % (inverse to temperature), range 29-100
    soil moisture: low-skewed (~6% typical) with occasional irrigation/rain spikes

Normalisation bounds match the q01/q99 statistics used by the real pipeline, so
synthetic ``*_norm`` values land in the same distribution the model trained on.

Values are deterministic per timestamp (seeded), so the same window always yields
the same vector - reproducible for the augmented training set and for tests.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict


@dataclass
class Calibration:
    # temperature (C)
    base_t: float = 15.7
    amp_t: float = 6.3
    noise_t: float = 1.4
    t_lo: float = 2.0
    t_hi: float = 32.4
    # humidity (%)
    base_h: float = 71.0
    amp_h: float = 16.8
    noise_h: float = 4.0
    th_coupling: float = 0.8     # humidity falls as temperature rises
    h_lo: float = 29.0
    h_hi: float = 100.0
    # soil moisture (%)
    p_wet_day: float = 0.20
    soil_dry_base: float = 6.0
    soil_dry_sigma: float = 0.45
    soil_wet_lo: float = 25.0
    soil_wet_hi: float = 80.0
    soil_noise: float = 0.8
    s_lo: float = 2.5
    s_hi: float = 97.0
    # normalisation bounds (q01/q99 of the real data)
    norm: Dict[str, tuple] = field(default_factory=lambda: {
        "soil_moisture": (2.62, 78.40),
        "temperature": (3.85, 29.00),
        "humidity": (37.00, 99.25),
    })


def _clip(x: float, lo: float, hi: float) -> float:
    return float(min(max(x, lo), hi))


class IoTSimulator:
    """Deterministic synthetic IoT context-vector generator."""

    def __init__(self, calibration: Calibration | None = None, seed: int = 42) -> None:
        self.c = calibration or Calibration()
        self.seed = int(seed)

    # ---- determinism helpers -------------------------------------------------
    @staticmethod
    def _to_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _rng(self, dt: datetime):
        import numpy as np
        sec = int(dt.timestamp())
        return np.random.default_rng((self.seed * 1_000_003 + sec) & 0xFFFFFFFF)

    def _day_rng(self, dt: datetime):
        import numpy as np
        return np.random.default_rng((self.seed * 7919 + dt.toordinal()) & 0xFFFFFFFF)

    # ---- generation ----------------------------------------------------------
    def raw_at(self, dt: datetime) -> Dict[str, float]:
        c = self.c
        dt = self._to_utc(dt)
        rng = self._rng(dt)
        drng = self._day_rng(dt)
        hour = dt.hour + dt.minute / 60.0
        phase = 2.0 * math.pi * (hour - 14.0) / 24.0  # peak temp at ~14:00

        temp = c.base_t + c.amp_t * math.cos(phase) + float(rng.normal(0, c.noise_t))
        temp = _clip(temp, c.t_lo, c.t_hi)

        hum = (c.base_h - c.amp_h * math.cos(phase) + float(rng.normal(0, c.noise_h))
               - c.th_coupling * (temp - c.base_t))
        hum = _clip(hum, c.h_lo, c.h_hi)

        if float(drng.random()) < c.p_wet_day:
            soil = float(drng.uniform(c.soil_wet_lo, c.soil_wet_hi))
        else:
            soil = c.soil_dry_base * math.exp(float(drng.normal(0, c.soil_dry_sigma)))
        soil = _clip(soil + float(rng.normal(0, c.soil_noise)), c.s_lo, c.s_hi)

        return {
            "soil_moisture": round(soil, 3),
            "temperature": round(temp, 3),
            "humidity": round(hum, 3),
        }

    def _normalize(self, raw: Dict[str, float]) -> Dict[str, float]:
        out = {}
        for k, v in raw.items():
            lo, hi = self.c.norm[k]
            out[k] = round(_clip((v - lo) / (hi - lo), 0.0, 1.0), 6)
        return out

    def vector_at(self, dt: datetime) -> Dict[str, object]:
        """One synthetic IoT context vector, clearly flagged as synthetic."""

        dt = self._to_utc(dt)
        raw = self.raw_at(dt)
        return {
            "timestamp_utc": dt.isoformat(),
            "raw": raw,
            "normalized": self._normalize(raw),
            "source": "synthetic",
            "generator": "agrispex_sim.IoTSimulator",
            "layout": "late_fusion_iot_context_vector_v1",
            "shape": [3],
        }

    def stream(self, start: datetime, end: datetime, freq_minutes: int = 60):
        """Yield synthetic vectors across a window (generator)."""

        from datetime import timedelta
        cur = self._to_utc(start)
        end = self._to_utc(end)
        step = timedelta(minutes=int(freq_minutes))
        while cur <= end:
            yield self.vector_at(cur)
            cur += step
