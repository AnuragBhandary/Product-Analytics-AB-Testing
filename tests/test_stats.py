from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats as sps

from ablab import stats


def test_compare_matches_welch_t_test_at_large_n() -> None:
    rng = np.random.default_rng(0)
    t, c = rng.normal(1.05, 2, 20_000), rng.normal(1.0, 3, 15_000)
    cmp = stats.compare(stats.Moments.of(t), stats.Moments.of(c))
    ref = sps.ttest_ind(t, c, equal_var=False)
    assert cmp.p_value == pytest.approx(ref.pvalue, rel=1e-3)
    assert cmp.ci_low < cmp.diff < cmp.ci_high
    assert cmp.rel_lift == pytest.approx(t.mean() / c.mean() - 1)


def test_binary_moments_use_unbiased_variance() -> None:
    m = stats.Moments.binary(10, 3)
    assert m.mean == 0.3
    assert m.var == pytest.approx(np.var([1] * 3 + [0] * 7, ddof=1))


def test_compare_zero_variance_gives_p_one() -> None:
    m = stats.Moments(10, 1.0, 0.0)
    assert stats.compare(m, m).p_value == 1.0


def test_relative_lift_ci_covers_truth_about_95_percent() -> None:
    rng = np.random.default_rng(1)
    hits = 0
    for _ in range(400):
        t = stats.Moments.binary(20_000, int(rng.binomial(20_000, 0.055)))
        c = stats.Moments.binary(20_000, int(rng.binomial(20_000, 0.05)))
        r = stats.compare(t, c)
        hits += r.rel_ci_low <= 0.1 <= r.rel_ci_high
    assert 0.92 <= hits / 400 <= 0.98


def test_srm_flags_skew_but_not_balance() -> None:
    assert stats.srm_test([50_000, 50_100], [0.5, 0.5]) > 0.5
    assert stats.srm_test([50_000, 51_500], [0.5, 0.5]) < 0.001
    assert stats.srm_test([150_000, 850_000], [0.15, 0.85]) == pytest.approx(1.0)


def test_required_n_gives_the_requested_power() -> None:
    p, rel = 0.10, 0.10
    n = stats.required_n_proportion(p, rel)
    se = math.sqrt(p * (1 - p) / n + 0.11 * 0.89 / n)
    assert stats.power_two_sample(se, 0.01) == pytest.approx(0.8, abs=0.002)
    # Unequal split needs more users in total than 50/50 for the same power.
    n_c = stats.required_n_proportion(p, rel, ratio=0.85 / 0.15)
    assert n_c * (1 + 0.85 / 0.15) > 2 * n


def test_mde_and_power_are_inverse() -> None:
    se = 0.002
    assert stats.power_two_sample(se, stats.mde_abs(se)) == pytest.approx(0.8, abs=1e-6)
    assert stats.power_two_sample(se, 0.0) == pytest.approx(0.05, abs=1e-9)


def test_cuped_is_unbiased_and_cuts_variance_by_rho_squared() -> None:
    rng = np.random.default_rng(2)
    n = 40_000
    x = rng.normal(0, 1, n)
    treat = rng.random(n) < 0.5
    y = 0.8 * x + rng.normal(0, 0.6, n) + 0.05 * treat
    adj = stats.cuped(y, x)
    rho2 = np.corrcoef(x, y)[0, 1] ** 2
    assert adj.variance_reduction == pytest.approx(rho2, abs=0.01)
    raw = stats.compare(stats.Moments.of(y[treat]), stats.Moments.of(y[~treat]))
    cup = stats.compare(stats.Moments.of(adj.y[treat]), stats.Moments.of(adj.y[~treat]))
    assert abs(cup.diff - 0.05) < 3 * cup.se
    assert cup.se < raw.se * 0.65


def test_cuped_constant_covariate_is_a_no_op() -> None:
    y = np.array([1.0, 2.0, 3.0])
    adj = stats.cuped(y, np.ones(3))
    assert adj.theta == 0.0 and adj.variance_reduction == 0.0
    np.testing.assert_array_equal(adj.y, y)


def test_delta_method_matches_ratio_spread_and_naive_is_too_narrow() -> None:
    """Users have several correlated sessions: session-level binomial SE underestimates."""
    rng = np.random.default_rng(3)
    ratios, delta_vars, naive_vars = [], [], []
    for _ in range(300):
        n = 3_000
        sessions = rng.integers(1, 8, n)
        propensity = rng.beta(0.3, 1.5, n)  # users differ a lot: sessions are correlated
        conv = rng.binomial(sessions, propensity)
        r, v = stats.ratio_moments(conv, sessions)
        ratios.append(r)
        delta_vars.append(v)
        naive_vars.append(r * (1 - r) / sessions.sum())
    emp = np.var(ratios, ddof=1)
    assert np.mean(delta_vars) == pytest.approx(emp, rel=0.2)
    assert np.mean(naive_vars) < 0.6 * emp


def test_compare_ratio_reports_the_ratio_difference() -> None:
    num_t, den_t = np.array([1, 0, 2, 1]), np.array([2, 1, 3, 2])
    num_c, den_c = np.array([0, 1, 1, 0]), np.array([2, 2, 3, 1])
    cmp = stats.compare_ratio(num_t, den_t, num_c, den_c)
    assert cmp.diff == pytest.approx(4 / 8 - 2 / 8)


def _sequential(effect: float, rng: np.random.Generator, looks: int = 30, per_look: int = 400):
    t = rng.normal(effect, 1, looks * per_look)
    c = rng.normal(0, 1, looks * per_look)
    ns = np.arange(1, looks + 1) * per_look
    diffs = np.array([t[:n].mean() - c[:n].mean() for n in ns])
    var = 2 / ns
    return diffs, var


def test_msprt_controls_type_one_error_under_continuous_peeking() -> None:
    rng = np.random.default_rng(4)
    naive_hits = msprt_hits = 0
    sims = 400
    for _ in range(sims):
        d, v = _sequential(0.0, rng)
        naive_hits += bool(np.any(2 * sps.norm.sf(np.abs(d) / np.sqrt(v)) < 0.05))
        msprt_hits += bool(np.any(stats.msprt_p_values(d, v, tau2=0.01) < 0.05))
    assert naive_hits / sims > 0.15  # peeking 30 times inflates a nominal 5% test
    assert msprt_hits / sims <= 0.06


def test_msprt_p_values_are_monotone_and_detect_real_effects() -> None:
    rng = np.random.default_rng(5)
    d, v = _sequential(0.1, rng)
    p = stats.msprt_p_values(d, v, tau2=0.01)
    assert np.all(np.diff(p) <= 0)
    assert p[-1] < 0.05


def test_bh_and_holm_match_hand_computed_values() -> None:
    p = [0.01, 0.04, 0.03, 0.005]
    np.testing.assert_allclose(stats.benjamini_hochberg(p), [0.02, 0.04, 0.04, 0.02])
    np.testing.assert_allclose(stats.holm(p), [0.03, 0.06, 0.06, 0.02])


def test_complier_effect_scales_itt_by_exposure() -> None:
    itt = stats.compare(stats.Moments.binary(100_000, 6_000), stats.Moments.binary(100_000, 5_000))
    out = stats.complier_effect(itt, 0.25, 100_000)
    assert out["cace"] == pytest.approx(itt.diff / 0.25)
    assert out["ci_low"] < out["cace"] < out["ci_high"]


def test_poisson_bootstrap_brackets_the_difference() -> None:
    rng = np.random.default_rng(6)
    t, c = rng.exponential(1.2, 4_000), rng.exponential(1.0, 4_000)
    lo, hi = stats.poisson_bootstrap_diff(t, c, reps=300)
    assert lo < t.mean() - c.mean() < hi
    assert lo < 0.2 < hi
