"""Experiment statistics, written out so every formula is visible and testable.

Everything works from sufficient statistics (n, mean, variance) where it can, so a 14M-row
experiment is summarised in SQL and only a handful of numbers reach Python.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy import stats as sps


@dataclass(frozen=True)
class Moments:
    """Sample size, mean and (unbiased) variance of one arm's per-unit metric."""

    n: int
    mean: float
    var: float

    @classmethod
    def of(cls, x: ArrayLike) -> Moments:
        a = np.asarray(x, dtype=float)
        return cls(int(a.size), float(a.mean()), float(a.var(ddof=1)))

    @classmethod
    def binary(cls, n: int, successes: int) -> Moments:
        p = successes / n
        return cls(n, p, p * (1 - p) * n / (n - 1))


@dataclass(frozen=True)
class Comparison:
    """Treatment minus control, absolute and relative, with a two-sided test."""

    control_mean: float
    treatment_mean: float
    diff: float
    se: float
    ci_low: float
    ci_high: float
    p_value: float
    rel_lift: float
    rel_ci_low: float
    rel_ci_high: float

    def as_dict(self) -> dict[str, float]:
        return {k: float(v) for k, v in self.__dict__.items()}


def _z(alpha: float) -> float:
    return float(sps.norm.ppf(1 - alpha / 2))


def compare(t: Moments, c: Moments, alpha: float = 0.05) -> Comparison:
    """Welch (unpooled) difference in means; relative lift CI by the delta method.

    With thousands of units per arm the normal reference is exact enough, and the same code
    covers conversion rates (binary moments) and revenue per user.
    """
    diff = t.mean - c.mean
    vt, vc = t.var / t.n, c.var / c.n
    se = math.sqrt(vt + vc)
    z = _z(alpha)
    p = 2 * sps.norm.sf(abs(diff) / se) if se > 0 else 1.0
    # lift = mt / mc - 1. Var(mt/mc) ~ vt / mc^2 + mt^2 vc / mc^4 (independent arms).
    rel = t.mean / c.mean - 1
    rel_se = math.sqrt(vt / c.mean**2 + t.mean**2 * vc / c.mean**4)
    return Comparison(
        control_mean=c.mean,
        treatment_mean=t.mean,
        diff=diff,
        se=se,
        ci_low=diff - z * se,
        ci_high=diff + z * se,
        p_value=float(p),
        rel_lift=rel,
        rel_ci_low=rel - z * rel_se,
        rel_ci_high=rel + z * rel_se,
    )


# --- sample ratio mismatch -------------------------------------------------------------


def srm_test(counts: Sequence[int], expected: Sequence[float]) -> float:
    """Chi-square goodness of fit of arm sizes against the designed split. Returns the p-value.

    Convention: alarm at p < 0.001, because the check runs on every experiment and a broken
    split invalidates everything downstream.
    """
    obs = np.asarray(counts, dtype=float)
    exp_share = np.asarray(expected, dtype=float)
    exp = obs.sum() * exp_share / exp_share.sum()
    return float(sps.chisquare(obs, exp).pvalue)


# --- power ------------------------------------------------------------------------------


def required_n_per_control(
    sigma_c: float,
    mde_abs: float,
    alpha: float = 0.05,
    power: float = 0.8,
    ratio: float = 1.0,
    sigma_t: float | None = None,
) -> int:
    """Control-arm units needed to detect an absolute difference `mde_abs` (two-sided).

    `ratio` = treatment units per control unit. Total units = n_c * (1 + ratio).
    """
    sigma_t = sigma_c if sigma_t is None else sigma_t
    z = _z(alpha) + float(sps.norm.ppf(power))
    return math.ceil(z**2 * (sigma_c**2 + sigma_t**2 / ratio) / mde_abs**2)


def required_n_proportion(
    p_c: float, rel_mde: float, alpha: float = 0.05, power: float = 0.8, ratio: float = 1.0
) -> int:
    """Control-arm units to detect a relative lift `rel_mde` on a conversion rate `p_c`."""
    p_t = p_c * (1 + rel_mde)
    return required_n_per_control(
        math.sqrt(p_c * (1 - p_c)),
        p_t - p_c,
        alpha,
        power,
        ratio,
        sigma_t=math.sqrt(p_t * (1 - p_t)),
    )


def power_two_sample(se: float, true_diff: float, alpha: float = 0.05) -> float:
    """Probability a two-sided z-test rejects, given the standard error of the difference."""
    z = _z(alpha)
    d = abs(true_diff) / se
    return float(sps.norm.sf(z - d) + sps.norm.cdf(-z - d))


def mde_abs(se: float, alpha: float = 0.05, power: float = 0.8) -> float:
    """Smallest absolute difference detectable with the given power at this standard error."""
    return (_z(alpha) + float(sps.norm.ppf(power))) * se


# --- variance reduction -----------------------------------------------------------------


@dataclass(frozen=True)
class Adjusted:
    """Outcome after CUPED adjustment and how much variance the adjustment removed."""

    y: NDArray[np.float64]
    theta: float
    variance_reduction: float


def cuped(y: ArrayLike, x: ArrayLike) -> Adjusted:
    """CUPED (Deng et al. 2013): y - theta * (x - mean(x)), theta = cov(y, x) / var(x).

    `x` must be fixed before assignment (pre-period metric, or a model prediction from
    pre-assignment features), so it is independent of treatment and the estimate stays unbiased.
    theta is pooled across arms, the standard choice.
    """
    ya = np.asarray(y, dtype=float)
    xa = np.asarray(x, dtype=float)
    vx = xa.var()
    if vx == 0:
        return Adjusted(ya.copy(), 0.0, 0.0)
    theta = float(np.mean((ya - ya.mean()) * (xa - xa.mean())) / vx)
    adj = ya - theta * (xa - xa.mean())
    vr = 1 - adj.var() / ya.var() if ya.var() > 0 else 0.0
    return Adjusted(adj, theta, float(vr))


# --- ratio metrics (randomised by user, measured per session) ---------------------------


def ratio_moments(num: ArrayLike, den: ArrayLike) -> tuple[float, float]:
    """Ratio sum(num)/sum(den) over users and its delta-method variance.

    When the unit of randomisation (user) differs from the unit of analysis (session),
    sessions are not independent and the naive binomial variance is too small.
    Var(R) ~ (1/n mu_d^2) [var_n - 2 R cov_nd + R^2 var_d]   (Deng et al. 2018).
    """
    a = np.asarray(num, dtype=float)
    b = np.asarray(den, dtype=float)
    n = a.size
    mu_n, mu_d = a.mean(), b.mean()
    r = mu_n / mu_d
    cov = np.cov(a, b, ddof=1)
    var = (cov[0, 0] - 2 * r * cov[0, 1] + r**2 * cov[1, 1]) / (n * mu_d**2)
    return float(r), float(var)


def compare_ratio(
    num_t: ArrayLike, den_t: ArrayLike, num_c: ArrayLike, den_c: ArrayLike, alpha: float = 0.05
) -> Comparison:
    rt, vt = ratio_moments(num_t, den_t)
    rc, vc = ratio_moments(num_c, den_c)
    # Express each arm as Moments with n=1 so compare() uses the delta variances directly.
    return compare(Moments(1, rt, vt), Moments(1, rc, vc), alpha)


# --- sequential testing ------------------------------------------------------------------


def msprt_p_values(diffs: ArrayLike, variances: ArrayLike, tau2: float) -> NDArray[np.float64]:
    """Always-valid p-values for a running difference in means (normal-mixture mSPRT).

    At each look k with estimate d_k and variance v_k (= Var of d_k), the mixture likelihood
    ratio against H0: delta = 0 with prior delta ~ N(0, tau2) is
        L_k = sqrt(v_k / (v_k + tau2)) * exp(tau2 * d_k^2 / (2 v_k (v_k + tau2)))
    and p_k = min(p_{k-1}, 1 / L_k). Rejecting whenever p_k < alpha keeps the type I error
    at alpha however often you look (Johari et al. 2017).
    """
    d = np.asarray(diffs, dtype=float)
    v = np.asarray(variances, dtype=float)
    log_l = 0.5 * np.log(v / (v + tau2)) + tau2 * d**2 / (2 * v * (v + tau2))
    p = np.minimum(1.0, np.exp(-log_l))
    return np.minimum.accumulate(p)


# --- multiple comparisons ---------------------------------------------------------------


def benjamini_hochberg(p_values: ArrayLike) -> NDArray[np.float64]:
    """BH-adjusted p-values (false discovery rate), same order as the input."""
    p = np.asarray(p_values, dtype=float)
    m = p.size
    order = np.argsort(p)
    ranked = p[order] * m / np.arange(1, m + 1)
    adj = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(m)
    out[order] = np.minimum(adj, 1.0)
    return out


def holm(p_values: ArrayLike) -> NDArray[np.float64]:
    """Holm step-down adjusted p-values (family-wise error), same order as the input."""
    p = np.asarray(p_values, dtype=float)
    m = p.size
    order = np.argsort(p)
    stepped = p[order] * (m - np.arange(m))
    adj = np.maximum.accumulate(stepped)
    out = np.empty(m)
    out[order] = np.minimum(adj, 1.0)
    return out


# --- non-compliance ---------------------------------------------------------------------


def complier_effect(itt: Comparison, exposure_rate_t: float, n_t: int) -> dict[str, float]:
    """Effect on users who were actually exposed (CACE / Wald estimator).

    Valid when control users cannot be exposed (one-sided non-compliance) and assignment only
    affects outcomes through exposure. The exposure rate's own sampling error is tiny next to
    the ITT error at these sample sizes, but it is included by the delta method.
    """
    e = exposure_rate_t
    var_e = e * (1 - e) / n_t
    est = itt.diff / e
    se = math.sqrt(itt.se**2 / e**2 + itt.diff**2 * var_e / e**4)
    z = _z(0.05)
    return {"cace": est, "se": se, "ci_low": est - z * se, "ci_high": est + z * se}


# --- bootstrap --------------------------------------------------------------------------


def poisson_bootstrap_diff(
    x_t: ArrayLike, x_c: ArrayLike, reps: int = 1000, seed: int = 0, alpha: float = 0.05
) -> tuple[float, float]:
    """Percentile CI for mean(t) - mean(c) with Poisson(1) weights (streaming-friendly)."""
    rng = np.random.default_rng(seed)
    t = np.asarray(x_t, dtype=float)
    c = np.asarray(x_c, dtype=float)
    out = np.empty(reps)
    for i in range(reps):
        wt = rng.poisson(1.0, t.size)
        wc = rng.poisson(1.0, c.size)
        out[i] = (wt @ t) / max(wt.sum(), 1) - (wc @ c) / max(wc.sum(), 1)
    lo, hi = np.quantile(out, [alpha / 2, 1 - alpha / 2])
    return float(lo), float(hi)
