"""Readout of a real randomised experiment: Criteo's incrementality test (13,979,592 users).

Treatment users could be shown ads; control users were held out. Outcomes are a site visit and
a conversion. The readout follows the order a real analysis should: check the split (SRM),
check covariate balance, then estimate the effect, then effect on the exposed and who responds.

The balance check fails on this release (the file pools several incrementality tests and was
subsampled), so the naive difference in means is not trusted on its own: the readout reports
it next to estimators that adjust for the imbalance and checks that those agree.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
from numpy.typing import NDArray
from scipy import stats as sps
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

from ablab import stats

FEATURES = [f"f{i}" for i in range(12)]
OUTCOMES = ["visit", "conversion"]
DESIGN_TREATMENT_SHARE = 0.85
PROPENSITY_CLIP = (0.01, 0.99)

F32 = NDArray[np.float32]
F64 = NDArray[np.float64]
I8 = NDArray[np.int8]


def connect(threads: int = 4) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"SET threads={threads}")
    return con


def to_parquet(csv_gz: Path, parquet: Path, threads: int = 4) -> None:
    con = connect(threads)
    con.execute(f"COPY (SELECT * FROM read_csv_auto('{csv_gz}')) TO '{parquet}' (FORMAT parquet)")


def arm_counts(con: duckdb.DuckDBPyConnection, parquet: Path) -> dict[int, dict[str, int]]:
    rows = con.execute(
        f"""SELECT treatment, count(*) AS n, sum(visit) AS visit, sum(conversion) AS conversion,
                   sum(exposure) AS exposure
            FROM '{parquet}' GROUP BY treatment ORDER BY treatment"""
    ).fetchall()
    return {
        int(t): {"n": int(n), "visit": int(v), "conversion": int(c), "exposure": int(e)}
        for t, n, v, c, e in rows
    }


def itt(arms: dict[int, dict[str, int]], outcome: str) -> stats.Comparison:
    t = stats.Moments.binary(arms[1]["n"], arms[1][outcome])
    c = stats.Moments.binary(arms[0]["n"], arms[0][outcome])
    return stats.compare(t, c)


def load_arrays(con: duckdb.DuckDBPyConnection, parquet: Path) -> tuple[F32, dict[str, I8]]:
    cols = ", ".join(FEATURES)
    res = con.execute(
        f"SELECT {cols}, treatment, visit, conversion, exposure FROM '{parquet}'"
    ).fetchnumpy()
    x = np.column_stack([res[f].astype(np.float32) for f in FEATURES])
    ys = {k: res[k].astype(np.int8) for k in ("treatment", "visit", "conversion", "exposure")}
    return x, ys


# --- balance ---------------------------------------------------------------------------


def balance(x: F32, treatment: I8) -> list[dict[str, Any]]:
    """Standardised mean difference per feature, and how many standard errors that is.

    Under randomisation an SMD's standard error is about sqrt(1/n_t + 1/n_c); at 14M users
    that is ~0.0008, so an SMD of 0.04 is far outside chance even though 0.1 is the usual
    "small" rule of thumb for observational studies.
    """
    t = treatment == 1
    n_t, n_c = int(t.sum()), int((~t).sum())
    se = math.sqrt(1 / n_t + 1 / n_c)
    out = []
    for j, name in enumerate(FEATURES):
        col = x[:, j].astype(np.float64)
        smd = (col[t].mean() - col[~t].mean()) / col.std()
        out.append({"feature": name, "smd": float(smd), "z": float(smd / se)})
    return out


def folds(n: int, seed: int = 0) -> I8:
    return np.random.default_rng(seed).integers(0, 2, size=n).astype(np.int8)


def _fit_predict(
    x: F32,
    y: I8,
    train_mask: NDArray[np.bool_],
    predict_mask: NDArray[np.bool_],
    train_rows: int,
    rng: np.random.Generator,
    seed: int,
) -> F64:
    train_idx = np.flatnonzero(train_mask)
    if train_idx.size > train_rows:
        train_idx = rng.choice(train_idx, train_rows, replace=False)
    model = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.1, random_state=seed)
    model.fit(x[train_idx], y[train_idx])
    idx = np.flatnonzero(predict_mask)
    out = np.empty(idx.size, dtype=np.float64)
    for chunk in np.array_split(np.arange(idx.size), max(1, idx.size // 1_000_000)):
        out[chunk] = model.predict_proba(x[idx[chunk]])[:, 1]
    return out


def cross_fit(
    x: F32,
    y: I8,
    fold: I8,
    train_filter: NDArray[np.bool_] | None = None,
    train_rows: int = 400_000,
    seed: int = 0,
) -> F64:
    """Out-of-fold predictions: the model that scores fold k never saw fold k.

    `train_filter` restricts training rows (e.g. control users only for a baseline model).
    """
    rng = np.random.default_rng(seed)
    pred = np.empty(y.size, dtype=np.float64)
    keep = np.ones(y.size, dtype=bool) if train_filter is None else train_filter
    for k in (0, 1):
        pred[fold == k] = _fit_predict(x, y, (fold != k) & keep, fold == k, train_rows, rng, seed)
    return pred


def treatment_auc(propensity: F64, treatment: I8) -> dict[str, float]:
    """Out-of-fold AUC of predicting assignment from features (0.5 under randomisation)."""
    auc = float(roc_auc_score(treatment, propensity))
    n1, n0 = int(treatment.sum()), int((treatment == 0).sum())
    # Mann-Whitney null standard error of the AUC.
    se0 = math.sqrt((n1 + n0 + 1) / (12 * n1 * n0))
    q = np.quantile(propensity, [0.01, 0.05, 0.5, 0.95, 0.99])
    return {
        "auc": auc,
        "z_vs_0.5": (auc - 0.5) / se0,
        "propensity_p01": float(q[0]),
        "propensity_p05": float(q[1]),
        "propensity_p50": float(q[2]),
        "propensity_p95": float(q[3]),
        "propensity_p99": float(q[4]),
    }


# --- estimators -------------------------------------------------------------------------


def _estimate(psi: F64, label: str, baseline: float) -> dict[str, float | str]:
    est = float(psi.mean())
    se = float(psi.std(ddof=1) / math.sqrt(psi.size))
    return {
        "estimator": label,
        "diff": est,
        "se": se,
        "ci_low": est - 1.96 * se,
        "ci_high": est + 1.96 * se,
        "p_value": float(2 * sps.norm.sf(abs(est) / se)),
        "rel_lift": est / baseline,
    }


def aipw_scores(y: I8, treatment: I8, e: F64, mu1: F64, mu0: F64) -> F64:
    """Doubly-robust (AIPW) influence scores; their mean is the average treatment effect.

    Consistent if either the propensity model or the outcome models are right.
    """
    t = treatment.astype(np.float64)
    yy = y.astype(np.float64)
    return mu1 - mu0 + t * (yy - mu1) / e - (1 - t) * (yy - mu0) / (1 - e)


def ipw_scores(y: I8, treatment: I8, e: F64) -> F64:
    """Horvitz-Thompson style inverse-propensity scores (unbiased, noisier than AIPW)."""
    t = treatment.astype(np.float64)
    yy = y.astype(np.float64)
    return t * yy / e - (1 - t) * yy / (1 - e)


def stratified(y: I8, treatment: I8, e: F64, strata: int = 20) -> dict[str, float | str]:
    """Post-stratify on propensity quantiles: compare arms within strata, weight by stratum size."""
    edges = np.quantile(e, np.linspace(0, 1, strata + 1))
    s = np.clip(np.searchsorted(edges, e, side="right") - 1, 0, strata - 1)
    est, var, n = 0.0, 0.0, y.size
    for k in range(strata):
        m = s == k
        yt, yc = y[m & (treatment == 1)], y[m & (treatment == 0)]
        if yt.size < 2 or yc.size < 2:
            continue
        w = m.sum() / n
        mt, mc = yt.mean(), yc.mean()
        est += w * (mt - mc)
        var += w**2 * (yt.var(ddof=1) / yt.size + yc.var(ddof=1) / yc.size)
    se = math.sqrt(var)
    base = float(y[treatment == 0].mean())
    return {
        "estimator": f"propensity-stratified ({strata} strata)",
        "diff": est,
        "se": se,
        "ci_low": est - 1.96 * se,
        "ci_high": est + 1.96 * se,
        "p_value": float(2 * sps.norm.sf(abs(est) / se)),
        "rel_lift": est / base,
    }


def segment_effects(
    psi: F64, score: F64, n_segments: int = 10, seed: int = 0
) -> list[dict[str, float]]:
    """Effect by decile of predicted baseline rate, from AIPW scores, BH-adjusted.

    Segments use a control-trained, cross-fitted score: pre-assignment information only, so this
    is not post-treatment slicing. Per-segment AIPW means stay valid under the imbalance.
    """
    # Equal-sized segments by rank. Many users share a predicted score, so quantile edges
    # collide; ties are broken at random (never by row order, which could track assignment).
    tiebreak = np.random.default_rng(seed).random(score.size)
    order = np.lexsort((tiebreak, score))
    seg = np.empty(score.size, dtype=np.int64)
    seg[order] = np.arange(score.size) * n_segments // score.size
    rows: list[dict[str, float]] = []
    for s in range(n_segments):
        p = psi[seg == s]
        est = float(p.mean())
        se = float(p.std(ddof=1) / math.sqrt(p.size))
        rows.append(
            {
                "segment": s + 1,
                "users": int(p.size),
                "mean_score": float(score[seg == s].mean()),
                "diff": est,
                "ci_low": est - 1.96 * se,
                "ci_high": est + 1.96 * se,
                "p_value": float(2 * sps.norm.sf(abs(est) / se)),
                "incremental_outcomes": est * p.size,
            }
        )
    adj = stats.benjamini_hochberg([r["p_value"] for r in rows])
    total = sum(r["incremental_outcomes"] for r in rows)
    for r, a in zip(rows, adj, strict=True):
        r["p_bh"] = float(a)
        r["share_of_incremental"] = r["incremental_outcomes"] / total
    return rows


def complier_effect_dr(psi_y: F64, psi_e: F64) -> dict[str, float]:
    """Effect on exposed users: ratio of doubly-robust effects on outcome and on exposure."""
    a, b = float(psi_y.mean()), float(psi_e.mean())
    cace = a / b
    infl = (psi_y - cace * psi_e) / b
    se = float(infl.std(ddof=1) / math.sqrt(infl.size))
    return {"cace": cace, "se": se, "ci_low": cace - 1.96 * se, "ci_high": cace + 1.96 * se}


# --- validating the test itself ---------------------------------------------------------


def empirical_power(
    y: I8,
    treatment: I8,
    sample_sizes: list[int],
    true_diff: float,
    reps: int = 1000,
    seed: int = 0,
) -> list[dict[str, float]]:
    """Draw many subsampled experiments; compare the rejection rate to the power formula.

    The full-data value of the same estimator stands in for the truth (its standard error is
    far smaller than any subsample's). If the formula is right, predicted and observed agree.
    """
    rng = np.random.default_rng(seed)
    pc = float(y[treatment == 0].mean())
    pt = pc + true_diff
    out = []
    for n in sample_sizes:
        rejections = 0
        for _ in range(reps):
            idx = rng.integers(0, y.size, size=n)
            yy, tt = y[idx], treatment[idx] == 1
            cmp = stats.compare(
                stats.Moments.binary(int(tt.sum()), int(yy[tt].sum())),
                stats.Moments.binary(int((~tt).sum()), int(yy[~tt].sum())),
            )
            rejections += cmp.p_value < 0.05
        nt, nc = n * DESIGN_TREATMENT_SHARE, n * (1 - DESIGN_TREATMENT_SHARE)
        se = math.sqrt(pt * (1 - pt) / nt + pc * (1 - pc) / nc)
        out.append(
            {
                "users": n,
                "predicted_power": stats.power_two_sample(se, true_diff),
                "observed_power": rejections / reps,
                "reps": reps,
            }
        )
    return out


def aa_false_positive_rate(y: I8, treatment: I8, n: int, reps: int = 1000, seed: int = 1) -> float:
    """Split control users at random into two fake arms many times; share of p < 0.05."""
    rng = np.random.default_rng(seed)
    ctrl = y[treatment == 0]
    hits = 0
    for _ in range(reps):
        sample = ctrl[rng.integers(0, ctrl.size, size=n)]
        a = rng.random(n) < 0.5
        cmp = stats.compare(
            stats.Moments.binary(int(a.sum()), int(sample[a].sum())),
            stats.Moments.binary(int((~a).sum()), int(sample[~a].sum())),
        )
        hits += cmp.p_value < 0.05
    return hits / reps


# --- the readout ------------------------------------------------------------------------


def readout(
    parquet: Path, threads: int = 4, seed: int = 0, validate: bool = True
) -> dict[str, Any]:
    con = connect(threads)
    arms = arm_counts(con, parquet)
    n_t, n_c = arms[1]["n"], arms[0]["n"]
    result: dict[str, Any] = {
        "users": n_t + n_c,
        "arms": arms,
        "treatment_share": n_t / (n_t + n_c),
        "srm_p_value": stats.srm_test(
            [n_c, n_t], [1 - DESIGN_TREATMENT_SHARE, DESIGN_TREATMENT_SHARE]
        ),
        "control_exposed": arms[0]["exposure"],
        "exposure_rate_treatment": arms[1]["exposure"] / n_t,
        "naive": {o: itt(arms, o).as_dict() for o in OUTCOMES},
    }

    x, ys = load_arrays(con, parquet)
    t = ys["treatment"]
    fold = folds(t.size, seed)
    result["balance"] = balance(x, t)

    e = cross_fit(x, t, fold, train_rows=1_000_000, seed=seed)
    result["treatment_predictability"] = treatment_auc(e, t)
    e = np.clip(e, *PROPENSITY_CLIP)

    result["estimates"] = {}
    result["segments"] = {}
    psis: dict[str, F64] = {}
    # Conversion is rare (0.2%), so its outcome models get more training rows.
    rows = {"visit": 400_000, "conversion": 2_000_000, "exposure": 400_000}
    for o in [*OUTCOMES, "exposure"]:
        y = ys[o]
        treated, control = t == 1, t == 0
        mu1 = cross_fit(x, y, fold, treated, rows[o], seed)
        mu0 = cross_fit(x, y, fold, control, rows[o], seed)
        psi = aipw_scores(y, t, e, mu1, mu0)
        psis[o] = psi
        if o == "exposure":
            continue
        base = float(y[control].mean())
        naive = result["naive"][o]
        adj = stats.cuped(y.astype(np.float64), mu0)
        cuped_cmp = stats.compare(
            stats.Moments.of(adj.y[treated]), stats.Moments.of(adj.y[control])
        )
        result["estimates"][o] = [
            {
                "estimator": "difference in means (naive)",
                "diff": naive["diff"],
                "se": naive["se"],
                "ci_low": naive["ci_low"],
                "ci_high": naive["ci_high"],
                "p_value": naive["p_value"],
                "rel_lift": naive["rel_lift"],
            },
            {
                "estimator": "CUPAC (CUPED on cross-fitted baseline prediction)",
                "diff": cuped_cmp.diff,
                "se": cuped_cmp.se,
                "ci_low": cuped_cmp.ci_low,
                "ci_high": cuped_cmp.ci_high,
                "p_value": cuped_cmp.p_value,
                "rel_lift": cuped_cmp.diff / base,
                "variance_reduction": adj.variance_reduction,
            },
            stratified(y, t, e),
            _estimate(ipw_scores(y, t, e), "inverse propensity weighting", base),
            _estimate(psi, "AIPW (doubly robust)", base),
        ]
        result["segments"][o] = segment_effects(psi, mu0, seed=seed)

    result["cace"] = {o: complier_effect_dr(psis[o], psis["exposure"]) for o in OUTCOMES}
    pc = arms[0]["conversion"] / n_c
    result["planning"] = {
        "baseline_conversion": pc,
        "users_for_10pct_conversion_lift_50_50": 2 * stats.required_n_proportion(pc, 0.10),
        "users_for_10pct_conversion_lift_85_15": math.ceil(
            stats.required_n_proportion(pc, 0.10, ratio=0.85 / 0.15) * (1 + 0.85 / 0.15)
        ),
    }

    if not validate:
        return result
    # Validating the z-test machinery on this data's real outcome distributions.
    result["power_check"] = {
        "visit": empirical_power(
            ys["visit"], t, [20_000, 50_000], result["naive"]["visit"]["diff"], seed=seed
        ),
        "conversion": empirical_power(
            ys["conversion"],
            t,
            [100_000, 200_000],
            result["naive"]["conversion"]["diff"],
            reps=500,
            seed=seed,
        ),
    }
    result["aa_false_positive_rate"] = {
        "visit_n100k_1000reps": aa_false_positive_rate(ys["visit"], t, 100_000, seed=seed + 1),
        "conversion_n1m_500reps": aa_false_positive_rate(
            ys["conversion"], t, 1_000_000, reps=500, seed=seed + 1
        ),
    }
    return result
