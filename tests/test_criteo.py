from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pytest

from ablab import criteo


def _confounded(path: Path, n: int = 60_000, seed: int = 0) -> float:
    """Two pooled 'tests' with different treatment shares and baselines; true effect 0.02."""
    rng = np.random.default_rng(seed)
    test_b = rng.random(n) < 0.3
    x = rng.normal(0, 1, (n, 12)).astype(np.float32)
    x[:, 0] += 10.0 * test_b  # f0 reveals which test a user came from (observed confounder)
    share = np.where(test_b, 0.95, 0.80)
    t = (rng.random(n) < share).astype(np.int8)
    base = np.where(test_b, 0.30, 0.05)
    exposure = (t == 1) & (rng.random(n) < 0.5)
    visit = (rng.random(n) < base + 0.04 * exposure).astype(np.int8)
    conversion = (visit == 1) & (rng.random(n) < 0.2)
    con = duckdb.connect()
    cols = {f"f{i}": x[:, i] for i in range(12)}
    cols |= {
        "treatment": t.astype(np.int64),
        "conversion": conversion.astype(np.int64),
        "visit": visit.astype(np.int64),
        "exposure": exposure.astype(np.int64),
    }
    con.register("df", con.from_arrow(__import__("pyarrow").table(cols)))
    con.execute(f"COPY df TO '{path}' (FORMAT parquet)")
    return 0.04 * 0.5  # ITT on visit = exposure effect x exposure rate


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict, float]:
    path = tmp_path_factory.mktemp("criteo") / "synthetic.parquet"
    truth = _confounded(path)
    return criteo.readout(path, threads=2, validate=False), truth


def test_naive_estimate_is_biased_by_pooling(result: tuple[dict, float]) -> None:
    r, truth = result
    naive = r["estimates"]["visit"][0]
    assert naive["ci_low"] > truth  # the high-baseline test is over-treated


def test_adjusted_estimators_recover_the_truth(result: tuple[dict, float]) -> None:
    r, truth = result
    for est in r["estimates"]["visit"][2:]:  # stratified, IPW, AIPW
        assert est["ci_low"] - 0.002 < truth < est["ci_high"] + 0.002, est["estimator"]


def test_balance_and_predictability_flag_the_problem(result: tuple[dict, float]) -> None:
    r, _ = result
    f0 = next(b for b in r["balance"] if b["feature"] == "f0")
    assert abs(f0["z"]) > 10
    assert r["treatment_predictability"]["auc"] > 0.55
    assert r["srm_p_value"] < 1  # computed, whatever its value


def test_complier_effect_recovers_exposure_effect(result: tuple[dict, float]) -> None:
    r, _ = result
    cace = r["cace"]["visit"]
    assert cace["ci_low"] - 0.01 < 0.04 < cace["ci_high"] + 0.01


def test_segments_partition_users_and_shares_sum_to_one(result: tuple[dict, float]) -> None:
    r, _ = result
    segs = r["segments"]["visit"]
    assert sum(s["users"] for s in segs) == r["users"]
    assert sum(s["share_of_incremental"] for s in segs) == pytest.approx(1.0)
    assert "planning" in r and "power_check" not in r


def test_aa_and_power_checks_behave() -> None:
    rng = np.random.default_rng(1)
    n = 200_000
    t = (rng.random(n) < 0.85).astype(np.int8)
    y = (rng.random(n) < 0.05 + 0.01 * t).astype(np.int8)
    fpr = criteo.aa_false_positive_rate(y, t, 20_000, reps=300)
    assert 0.02 <= fpr <= 0.09
    rows = criteo.empirical_power(y, t, [20_000], 0.01, reps=300)
    assert abs(rows[0]["observed_power"] - rows[0]["predicted_power"]) < 0.08


def test_to_parquet_round_trips(tmp_path: Path) -> None:
    import gzip

    csv = tmp_path / "x.csv.gz"
    with gzip.open(csv, "wt") as fh:
        fh.write("f0,treatment\n1.5,1\n2.5,0\n")
    out = tmp_path / "x.parquet"
    criteo.to_parquet(csv, out, threads=1)
    assert duckdb.connect().execute(f"SELECT sum(f0) FROM '{out}'").fetchone() == (4.0,)
