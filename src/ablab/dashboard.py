"""Build the small DuckDB file the Evidence dashboard and the Power BI CSVs read from.

Inputs: the exported marts (data/ga4/*.parquet) and the result JSONs (docs/results). Only
aggregates go in, so the file is small enough to commit and CI can build the site without
BigQuery credentials.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

MART_TABLES = [
    "mart_funnel_weekly",
    "mart_cohort_retention",
    "mart_daily_kpis",
    "mart_channel_performance",
    "mart_product_performance",
]


def _table(rows: list[dict[str, Any]]) -> pa.Table:
    return pa.Table.from_pylist(rows)


def result_tables(criteo: dict[str, Any], sims: dict[str, Any]) -> dict[str, pa.Table]:
    tables: dict[str, list[dict[str, Any]]] = {
        "criteo_estimates": [],
        "criteo_segments": [],
        "criteo_balance": criteo["balance"],
        "sim_calibration": [],
        "sim_peeking": sims["peeking"],
        "sim_srm": sims["srm"],
        "sim_metric_sensitivity": [],
    }
    for outcome, rows in criteo["estimates"].items():
        naive = rows[0]["diff"]
        for order, r in enumerate(rows):
            tables["criteo_estimates"].append(
                {
                    "outcome": outcome,
                    "estimator_order": order,
                    "estimator": r["estimator"],
                    "diff": r["diff"],
                    "ci_low": r["ci_low"],
                    "ci_high": r["ci_high"],
                    "rel_lift": r["rel_lift"],
                    "share_of_naive": r["diff"] / naive,
                }
            )
    for outcome, rows in criteo["segments"].items():
        for r in rows:
            tables["criteo_segments"].append({"outcome": outcome, **r})
    for lift_key, row in sims["calibration"].items():
        lift = float(lift_key.removeprefix("lift_"))
        for metric in (
            "conversion",
            "revenue",
            "revenue_capped",
            "revenue_cuped",
            "revenue_cupac",
            "session_rate_delta",
            "session_rate_naive",
        ):
            tables["sim_calibration"].append(
                {"lift": lift, "analysis": metric, "rejection_rate": row[metric]}
            )
    for block in sims["metric_sensitivity"]:
        for key, value in block.items():
            if key.startswith("days_"):
                tables["sim_metric_sensitivity"].append(
                    {
                        "rel_mde": block["rel_mde"],
                        "metric": key.removeprefix("days_"),
                        "days_needed": value,
                    }
                )
    return {k: _table(v) for k, v in tables.items()}


def build(ga4_dir: Path, results_dir: Path, out: Path) -> list[str]:
    criteo = json.loads((results_dir / "criteo-readout.json").read_text())
    sims = json.loads((results_dir / "ga4-simulations.json").read_text())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    con = duckdb.connect(str(out))
    for name in MART_TABLES:
        con.execute(
            f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{ga4_dir / name}.parquet')"
        )
    for name, table in result_tables(criteo, sims).items():
        con.register("t", table)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM t")
        con.unregister("t")
    names = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    con.close()
    return names


def export_csv(db: Path, out_dir: Path) -> list[Path]:
    """Every dashboard table as CSV: the Power BI fallback when BigQuery is not reachable."""
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db), read_only=True)
    paths = []
    for (name,) in con.execute("SHOW TABLES").fetchall():
        path = out_dir / f"{name}.csv"
        con.execute(f"COPY {name} TO '{path}' (HEADER, DELIMITER ',')")
        paths.append(path)
    return paths
