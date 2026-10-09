from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa
import pytest

from ablab import simulate


def _users(n: int = 20_000, days: int = 10, seed: int = 0) -> simulate.Users:
    """Skewed, GA4-like users: most never buy, buyers spend a lognormal amount."""
    rng = np.random.default_rng(seed)
    sessions = rng.integers(1, 5, n).astype(np.float64)
    propensity = rng.beta(0.2, 4, n)
    buyer = (rng.random(n) < propensity).astype(np.float64)
    revenue = buyer * rng.lognormal(4, 1, n)
    pre = 0.5 * revenue + buyer * rng.lognormal(3, 1, n) * (rng.random(n) < 0.3)
    arrival = rng.integers(0, days, n)
    daily = np.zeros((n, days), dtype=np.float32)
    buy_day = np.minimum(days - 1, arrival + rng.integers(0, 3, n))
    daily[np.arange(n), buy_day] = revenue
    return simulate.Users(
        arrival_day=arrival,
        sessions=sessions,
        converted_sessions=buyer * np.minimum(sessions, 1 + rng.integers(0, 2, n)),
        purchaser=buyer,
        carted=np.maximum(buyer, (rng.random(n) < 0.1).astype(np.float64)),
        revenue=revenue,
        pre_sessions=rng.poisson(1, n).astype(np.float64),
        pre_revenue=pre,
        covariate_pred=0.4 * revenue + rng.normal(0, 20, n),
        is_mobile=rng.random(n) < 0.4,
        daily_revenue_cum=np.cumsum(daily, axis=1, dtype=np.float32),
    )


def test_aa_calibration_near_five_percent_and_naive_session_test_overrejects() -> None:
    u = _users()
    r = simulate.calibration(u, [0.0], reps=200)["lift_0"]
    for key in (
        "conversion",
        "revenue",
        "revenue_capped",
        "revenue_cuped",
        "revenue_cupac",
        "session_rate_delta",
    ):
        assert r[key] <= 0.10, key
    assert r["session_rate_naive"] > r["session_rate_delta"]


def test_injected_lift_raises_power_and_cuped_helps() -> None:
    u = _users()
    r = simulate.calibration(u, [0.3], reps=150, seed=1)["lift_0.3"]
    assert r["conversion"] > 0.5
    assert r["revenue_cupac"] >= r["revenue"]
    assert r["variance_reduction_cupac"] > 0.1
    assert r["revenue_ci_coverage"] > 0.85
    assert r["mean_rel_revenue"] == pytest.approx(0.3, abs=0.1)


def test_peeking_inflates_naive_but_not_msprt() -> None:
    u = _users(n=8_000)
    r = simulate.peeking(u, reps=200)
    assert r["reject_naive_daily_peeking"] > r["reject_single_final_look"]
    assert r["reject_msprt_daily_peeking"] <= 0.08
    big = simulate.peeking(_users(n=40_000), reps=100, lift=1.0, tau_rel=0.5, seed=1)
    assert big["reject_msprt_daily_peeking"] > 0.5
    assert 1 <= big["msprt_median_stop_day"] <= u.days


def test_srm_catches_a_large_redirect_bug() -> None:
    u = _users()
    big = simulate.srm_detection(u, 0.8, reps=50)
    none = simulate.srm_detection(u, 0.0, reps=50)
    assert big["srm_alarm_rate"] > 0.9
    assert big["mean_false_rel_lift_conversion"] > 0.05
    assert none["srm_alarm_rate"] < 0.1


def test_required_days_falls_with_variance_reduction() -> None:
    r = simulate.required_days(_users(), 0.05)
    assert r["days_revenue_per_user_cupac"] < r["days_revenue_per_user"]
    assert r["days_revenue_per_user_capped_p99"] < r["days_revenue_per_user"]


def test_load_users_builds_cumulative_daily_revenue(tmp_path: Path) -> None:
    users = pa.table(
        {
            "user_pseudo_id": ["a", "b"],
            "arrival_day": [0, 1],
            "sessions": [2, 1],
            "converted_sessions": [1, 0],
            "purchaser": [1, 0],
            "carted": [1, 1],
            "revenue": [30.0, 0.0],
            "pre_sessions": [0, 3],
            "pre_revenue": [0.0, 5.0],
            "is_mobile": [True, False],
            "device_category": ["mobile", "desktop"],
            "country": ["India", "Japan"],
            "channel": ["Direct", "Referral"],
            "pre_purchases": [0, 1],
            "pre_cart_sessions": [0, 1],
        }
    )
    days = pa.table(
        {"user_pseudo_id": ["a", "a", "b"], "day_index": [0, 2, 1], "revenue": [10.0, 20.0, 0.0]}
    )
    con = duckdb.connect()
    for name, tbl in (("users", users), ("days", days)):
        con.register(name, tbl)
        con.execute(f"COPY {name} TO '{tmp_path / name}.parquet' (FORMAT parquet)")
    u = simulate.load_users(tmp_path / "users.parquet", tmp_path / "days.parquet", threads=1)
    assert u.n == 2 and u.days == 3
    np.testing.assert_allclose(u.daily_revenue_cum[0], [10, 10, 30])
    np.testing.assert_allclose(u.daily_revenue_cum[1], [0, 0, 0])
