"""Feature engineering: the training-side formulas the classifier depends on."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from generate_training import (  # noqa: E402
    simulate, features, slope_per_day, lag_corr, _roll_med_residual, CLASSES)
import random  # noqa: E402


def test_slope_recovers_known_trend():
    series = [10 + 2.0 * (i * 5 / 1440) for i in range(500)]  # 2.0/day
    assert abs(slope_per_day(series) - 2.0) < 1e-6


def test_slope_flat_series_is_zero():
    assert abs(slope_per_day([7.0] * 300)) < 1e-9


def test_lag_corr_detects_lagged_copy():
    rng = random.Random(0)
    a = [math.sin(i / 9) + rng.gauss(0, .05) for i in range(600)]
    b = [0.0] * 36 + a[:-36]
    assert lag_corr(a, b, lag=36) > 0.9


def test_roll_med_residual_removes_level_shift():
    series = [100.0] * 100 + [200.0] * 100
    res = _roll_med_residual(series)
    assert max(abs(r) for r in res[-50:]) < 1e-9  # settled after the step


def test_simulated_classes_have_expected_signatures():
    rng = random.Random(42)
    vib, temp, rpm, vb, tb, rb = simulate("FP-01", rng)
    f = features(vib, temp, rpm, vb, tb, rb)
    assert f["vib_ratio"] > 1.3          # bearing wear raises vibration
    rng = random.Random(43)
    vib, temp, rpm, vb, tb, rb = simulate("FP-02", rng)
    f2 = features(vib, temp, rpm, vb, tb, rb)
    assert f2["temp_z"] > 2.0            # cooling degradation raises temp
    assert f2["vib_ratio"] < 1.3         # ...without vibration
    rng = random.Random(44)
    vib, temp, rpm, vb, tb, rb = simulate("FP-03", rng)
    f3 = features(vib, temp, rpm, vb, tb, rb)
    assert f3["vib_std_recent"] < 0.05   # stuck sensor: variance collapses


def test_all_classes_simulate_without_error():
    rng = random.Random(1)
    for cls in CLASSES:
        vib, temp, rpm, vb, tb, rb = simulate(cls, rng)
        f = features(vib, temp, rpm, vb, tb, rb)
        assert all(isinstance(v, float) for v in f.values())
        assert not any(math.isnan(v) for v in f.values())
