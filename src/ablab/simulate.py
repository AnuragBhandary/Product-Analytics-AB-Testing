"""Testing the tests: thousands of simulated experiments on real GA4 users.

A real experiment cannot tell you whether your analysis is calibrated; you only see one draw.
Here the users, their sessions and their (very skewed) revenue are real, and only the
assignment is simulated. So the truth is known by construction:

* A/A: random split, no effect. A calibrated test rejects about 5% of the time.
* Injected lift: a known effect added to the treatment arm. The rejection rate is the power.
* Peeking: the same A/A tests looked at every day. Naive p-values reject far more than 5%;
  always-valid (mSPRT) p-values do not.
* Broken randomisation: drop a slice of treatment users, as a buggy redirect would, and see
  whether the SRM check catches it before the biased estimate is trusted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
from numpy.typing import NDArray

from ablab import stats

F64 = NDArray[np.float64]
B = NDArray[np.bool_]


@dataclass(frozen=True)
class Users:
    """One row per user who arrived during the experiment window."""

    arrival_day: NDArray[np.int64]  # 0-based day of first visit inside the window
    sessions: F64  # sessions in the window
    converted_sessions: F64  # sessions with a purchase
    purchaser: F64  # 1 if any purchase in the window
    carted: F64  # 1 if any add-to-cart in the window
    revenue: F64  # USD in the window
    pre_sessions: F64  # sessions before the window (CUPED covariate)
    pre_revenue: F64
    covariate_pred: F64  # cross-fitted prediction of revenue from pre-assignment features
    is_mobile: B
    daily_revenue_cum: NDArray[np.float32]  # users x days: revenue up to and including day d

    @property
    def n(self) -> int:
        return int(self.revenue.size)

    @property
    def days(self) -> int:
        return int(self.daily_revenue_cum.shape[1])


def load_users(user_parquet: Path, day_parquet: Path, threads: int = 4) -> Users:
    """Read the exported marts (see dbt models exp_users and exp_user_days)."""
    con = duckdb.connect()
    con.execute(f"SET threads={threads}")
    u = con.execute(
        f"""SELECT user_pseudo_id, arrival_day, sessions, converted_sessions, purchaser, carted,
                   revenue, pre_sessions, pre_revenue, is_mobile
            FROM '{user_parquet}' ORDER BY user_pseudo_id"""
    ).fetchnumpy()
    days = int(
        con.execute(f"SELECT max(day_index) + 1 FROM '{day_parquet}'").fetchone()[0]  # type: ignore[index]
    )
    d = con.execute(
        f"""SELECT u.rn, d.day_index, d.revenue
            FROM '{day_parquet}' d
            JOIN (SELECT user_pseudo_id, row_number() OVER (ORDER BY user_pseudo_id) - 1 AS rn
                  FROM '{user_parquet}') u USING (user_pseudo_id)
            WHERE d.revenue > 0"""
    ).fetchnumpy()
    n = len(u["user_pseudo_id"])
    daily = np.zeros((n, days), dtype=np.float32)
    np.add.at(daily, (d["rn"].astype(np.int64), d["day_index"].astype(np.int64)), d["revenue"])
    pred = cupac_covariate(user_parquet, threads)
    users = Users(
        arrival_day=u["arrival_day"].astype(np.int64),
        sessions=u["sessions"].astype(np.float64),
        converted_sessions=u["converted_sessions"].astype(np.float64),
        purchaser=u["purchaser"].astype(np.float64),
        carted=u["carted"].astype(np.float64),
        revenue=u["revenue"].astype(np.float64),
        pre_sessions=u["pre_sessions"].astype(np.float64),
        pre_revenue=u["pre_revenue"].astype(np.float64),
        covariate_pred=pred,
        is_mobile=u["is_mobile"].astype(bool),
        daily_revenue_cum=np.cumsum(daily, axis=1, dtype=np.float32),
    )
    return users


CATEGORICAL = ["device_category", "country", "channel"]
NUMERIC = ["arrival_day", "pre_sessions", "pre_purchases", "pre_revenue", "pre_cart_sessions"]


def cupac_covariate(user_parquet: Path, threads: int = 4, seed: int = 0) -> F64:
    """Cross-fitted prediction of window revenue from what is known at assignment.

    Features: device, country, acquisition channel of the arrival session, arrival day and
    pre-period activity. Two folds, each predicted by a model that never saw it, so the
    prediction is independent of the (simulated) assignment. Rows come back in
    user_pseudo_id order, matching load_users.
    """
    from sklearn.ensemble import HistGradientBoostingRegressor

    con = duckdb.connect()
    con.execute(f"SET threads={threads}")
    # Countries outside the top 30 share one level so the model sees each level enough.
    df = con.execute(
        f"""WITH top AS (SELECT country FROM '{user_parquet}' GROUP BY 1
                         ORDER BY count(*) DESC LIMIT 30)
            SELECT u.device_category,
                   CASE WHEN u.country IN (SELECT country FROM top) THEN u.country
                        ELSE 'other' END AS country,
                   u.channel, {", ".join("u." + c for c in NUMERIC)}, u.revenue
            FROM '{user_parquet}' u ORDER BY u.user_pseudo_id"""
    ).fetchnumpy()
    cols = []
    for c in CATEGORICAL:
        _, codes = np.unique(df[c].astype(str), return_inverse=True)
        cols.append(codes.astype(np.float64))
    cols += [df[c].astype(np.float64) for c in NUMERIC]
    x = np.column_stack(cols)
    y = df["revenue"].astype(np.float64)
    if y.size < 100:  # too few users to fit anything; a constant covariate is a no-op
        return np.zeros(y.size)
    fold = np.random.default_rng(seed).integers(0, 2, y.size)
    pred = np.empty(y.size)
    for k in (0, 1):
        model = HistGradientBoostingRegressor(
            max_iter=200,
            learning_rate=0.05,
            categorical_features=list(range(len(CATEGORICAL))),
            random_state=seed,
        )
        model.fit(x[fold != k], y[fold != k])
        pred[fold == k] = model.predict(x[fold == k])
    return pred


# --- one simulated experiment ------------------------------------------------------------


def _inject(u: Users, treat: B, lift: float, rng: np.random.Generator) -> tuple[F64, F64]:
    """Apply a relative lift to treatment users' conversion and revenue.

    Conversion: non-purchasing treatment users become purchasers with probability chosen so
    the expected purchaser rate rises by `lift`; they get a revenue drawn from real purchases.
    Existing revenue is unchanged, so revenue per user rises by about the same `lift`.
    """
    purchaser = u.purchaser.copy()
    revenue = u.revenue.copy()
    if lift == 0:
        return purchaser, revenue
    p = u.purchaser.mean()
    flip_prob = p * lift / (1 - p)
    candidates = treat & (purchaser == 0)
    flips = candidates & (rng.random(u.n) < flip_prob)
    real = u.revenue[u.purchaser == 1]
    purchaser[flips] = 1
    revenue[flips] = rng.choice(real, int(flips.sum()))
    return purchaser, revenue


def _cmp(y: F64, treat: B) -> stats.Comparison:
    return stats.compare(stats.Moments.of(y[treat]), stats.Moments.of(y[~treat]))


def run_once(u: Users, lift: float, rng: np.random.Generator) -> dict[str, float]:
    """p-values (and estimates) of every analysis variant on one random assignment."""
    treat = rng.random(u.n) < 0.5
    purchaser, revenue = _inject(u, treat, lift, rng)
    out: dict[str, float] = {}

    conv = _cmp(purchaser, treat)
    out["p_conversion"] = conv.p_value
    rev = _cmp(revenue, treat)
    out["p_revenue"] = rev.p_value
    out["rel_revenue"] = rev.rel_lift
    out["covered_revenue"] = float(rev.rel_ci_low <= lift <= rev.rel_ci_high)

    # Revenue capped at the pooled 99th percentile of purchasers: a common trade of a little
    # bias for a lot of variance. The cap is set from both arms together, never per arm.
    cap = capped(revenue)
    out["p_revenue_capped"] = _cmp(cap, treat).p_value

    cup = stats.cuped(revenue, u.pre_revenue)
    out["p_revenue_cuped"] = _cmp(cup.y, treat).p_value
    out["vr_cuped"] = cup.variance_reduction
    cupac = stats.cuped(revenue, u.covariate_pred)
    out["p_revenue_cupac"] = _cmp(cupac.y, treat).p_value
    out["vr_cupac"] = cupac.variance_reduction

    # Session conversion rate: randomised by user, analysed per session.
    conv_sessions = u.converted_sessions
    if lift:
        # Newly converted users bought in one of their sessions.
        extra = (purchaser == 1) & (u.purchaser == 0)
        conv_sessions = conv_sessions + extra
    ratio = stats.compare_ratio(
        conv_sessions[treat], u.sessions[treat], conv_sessions[~treat], u.sessions[~treat]
    )
    out["p_session_rate_delta"] = ratio.p_value
    st, sc = u.sessions[treat].sum(), u.sessions[~treat].sum()
    naive = stats.compare(
        stats.Moments.binary(int(st), int(conv_sessions[treat].sum())),
        stats.Moments.binary(int(sc), int(conv_sessions[~treat].sum())),
    )
    out["p_session_rate_naive"] = naive.p_value
    return out


def calibration(u: Users, lifts: list[float], reps: int, seed: int = 0) -> dict[str, Any]:
    """Rejection rates at alpha=0.05 for every variant, at each injected lift."""
    rng = np.random.default_rng(seed)
    result: dict[str, Any] = {}
    for lift in lifts:
        runs = [run_once(u, lift, rng) for _ in range(reps)]
        keys = [k for k in runs[0] if k.startswith("p_")]
        row: dict[str, float] = {
            k.removeprefix("p_"): float(np.mean([r[k] < 0.05 for r in runs])) for k in keys
        }
        row["revenue_ci_coverage"] = float(np.mean([r["covered_revenue"] for r in runs]))
        row["mean_rel_revenue"] = float(np.mean([r["rel_revenue"] for r in runs]))
        row["variance_reduction_cuped"] = float(np.mean([r["vr_cuped"] for r in runs]))
        row["variance_reduction_cupac"] = float(np.mean([r["vr_cupac"] for r in runs]))
        result[f"lift_{lift:g}"] = row
    return result


# --- peeking ----------------------------------------------------------------------------


def peeking(
    u: Users, reps: int, lift: float = 0.0, tau_rel: float = 0.05, seed: int = 0
) -> dict[str, float]:
    """Revenue-per-user tests analysed after every day of the window.

    On day d the analysis sees users who have arrived by d, with revenue up to d. Stopping at
    the first p < 0.05 is what a dashboard-watcher does. `lift` multiplies treatment revenue
    (0 = A/A). The mSPRT mixing scale is tau = tau_rel x mean revenue per user: the size of
    effect it is tuned to find.
    """
    rng = np.random.default_rng(seed)
    days = u.days
    arrived = u.arrival_day[:, None] <= np.arange(days)[None, :]
    cum = np.where(arrived, u.daily_revenue_cum, 0.0).astype(np.float64)
    cum2 = cum**2
    arrived_f = arrived.astype(np.float64)
    tau2 = (tau_rel * u.revenue.mean()) ** 2
    naive_any = msprt_any = final_only = 0
    stop_days: list[int] = []
    for _ in range(reps):
        a = (rng.random(u.n) < 0.5).astype(np.float64)
        b = 1 - a
        n_t, n_c = a @ arrived_f, b @ arrived_f
        s_t, s_c = (1 + lift) * (a @ cum), b @ cum
        q_t, q_c = (1 + lift) ** 2 * (a @ cum2), b @ cum2
        ok = (n_t > 1) & (n_c > 1)
        n_t, n_c, s_t, s_c, q_t, q_c = (v[ok] for v in (n_t, n_c, s_t, s_c, q_t, q_c))
        m_t, m_c = s_t / n_t, s_c / n_c
        v_t = (q_t - n_t * m_t**2) / (n_t - 1)
        v_c = (q_c - n_c * m_c**2) / (n_c - 1)
        var = v_t / n_t + v_c / n_c
        d = m_t - m_c
        p = 2 * (1 - _norm_cdf(np.abs(d) / np.sqrt(var)))
        naive_any += bool(np.any(p < 0.05))
        final_only += bool(p[-1] < 0.05)
        hits = np.flatnonzero(stats.msprt_p_values(d, var, tau2) < 0.05)
        if hits.size:
            msprt_any += 1
            stop_days.append(int(hits[0]) + 1)
    return {
        "lift": lift,
        "tau_rel": tau_rel,
        "looks": float(days),
        "reps": float(reps),
        "reject_single_final_look": final_only / reps,
        "reject_naive_daily_peeking": naive_any / reps,
        "reject_msprt_daily_peeking": msprt_any / reps,
        "msprt_median_stop_day": float(np.median(stop_days)) if stop_days else float("nan"),
    }


def _norm_cdf(z: F64) -> F64:
    from scipy.special import ndtr

    return np.asarray(ndtr(z), dtype=np.float64)


# --- broken randomisation ---------------------------------------------------------------


def srm_detection(
    u: Users, drop_share: float, reps: int, seed: int = 0, threshold: float = 0.001
) -> dict[str, float]:
    """A bug loses `drop_share` of treatment users who bounce (one session, no cart, no
    purchase): say the new page's script loads slowly and fast leavers are never logged.

    Losing low-value users from one arm only makes treatment look better. Measured: how
    often the SRM check fires (p < 0.001), and how often an unchecked analysis would declare
    a significant revenue or conversion "win" that does not exist.
    """
    rng = np.random.default_rng(seed)
    bouncer = (u.sessions == 1) & (u.carted == 0) & (u.revenue == 0)
    alarms = fake_rev = fake_conv = 0
    lifts = []
    for _ in range(reps):
        treat = rng.random(u.n) < 0.5
        lost = treat & bouncer & (rng.random(u.n) < drop_share)
        t, c = treat & ~lost, ~treat
        alarms += stats.srm_test([int(c.sum()), int(t.sum())], [0.5, 0.5]) < threshold
        rev = stats.compare(stats.Moments.of(u.revenue[t]), stats.Moments.of(u.revenue[c]))
        conv = stats.compare(
            stats.Moments.binary(int(t.sum()), int(u.purchaser[t].sum())),
            stats.Moments.binary(int(c.sum()), int(u.purchaser[c].sum())),
        )
        fake_rev += rev.p_value < 0.05
        fake_conv += conv.p_value < 0.05
        lifts.append(conv.rel_lift)
    return {
        "drop_share_of_treatment_bouncers": drop_share,
        "users_lost_share": float(drop_share * bouncer.mean() / 2),
        "srm_alarm_rate": alarms / reps,
        "false_revenue_win_rate": fake_rev / reps,
        "false_conversion_win_rate": fake_conv / reps,
        "mean_false_rel_lift_conversion": float(np.mean(lifts)),
    }


def capped(revenue: F64, quantile: float = 0.99) -> F64:
    """Winsorise revenue at a quantile of purchasers' revenue (pooled over both arms)."""
    buyers = revenue[revenue > 0]
    if buyers.size == 0:
        return revenue
    return np.minimum(revenue, np.quantile(buyers, quantile))


def required_days(u: Users, rel_mde: float, power: float = 0.8) -> dict[str, float]:
    """Days of this store's traffic for a 50/50 test to detect `rel_mde` on each metric.

    The same business question ("did the change help?") can be asked of noisier or quieter
    metrics; this is the table that decides which one an experiment should be powered on.
    """
    per_day = u.n / u.days
    out: dict[str, float] = {"users_per_day": per_day, "rel_mde": rel_mde}
    metrics = {
        "revenue_per_user": (u.revenue, 0.0),
        "revenue_per_user_cuped": (
            u.revenue,
            stats.cuped(u.revenue, u.pre_revenue).variance_reduction,
        ),
        "revenue_per_user_cupac": (
            u.revenue,
            stats.cuped(u.revenue, u.covariate_pred).variance_reduction,
        ),
        "revenue_per_user_capped_p99": (capped(u.revenue), 0.0),
        "purchaser_rate": (u.purchaser, 0.0),
        "add_to_cart_rate": (u.carted, 0.0),
    }
    for name, (y, vr) in metrics.items():
        sigma = float(y.std(ddof=1)) * math.sqrt(1 - vr)
        n_c = stats.required_n_per_control(sigma, rel_mde * float(y.mean()), power=power)
        out[f"days_{name}"] = 2 * n_c / per_day
        out[f"cv_{name}"] = float(y.std(ddof=1) / y.mean())
    return out
