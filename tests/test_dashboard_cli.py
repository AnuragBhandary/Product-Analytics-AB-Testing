from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ablab import cli, dashboard


def _results() -> tuple[dict, dict]:
    est = [
        {"estimator": n, "diff": d, "ci_low": d - 1, "ci_high": d + 1, "rel_lift": d / 10}
        for n, d in (("difference in means (naive)", 4.0), ("AIPW (doubly robust)", 3.0))
    ]
    criteo = {
        "balance": [{"feature": "f0", "smd": 0.01, "z": 12.0}],
        "estimates": {"visit": est},
        "segments": {"visit": [{"segment": 1, "diff": 0.1, "share_of_incremental": 1.0}]},
    }
    cal_row = {
        k: 0.05
        for k in (
            "conversion",
            "revenue",
            "revenue_capped",
            "revenue_cuped",
            "revenue_cupac",
            "session_rate_delta",
            "session_rate_naive",
        )
    }
    sims = {
        "calibration": {"lift_0": cal_row, "lift_0.1": cal_row},
        "peeking": [{"lift": 0.0, "reject_naive_daily_peeking": 0.3}],
        "srm": [{"drop_share_of_treatment_bouncers": 0.05, "srm_alarm_rate": 1.0}],
        "metric_sensitivity": [{"rel_mde": 0.1, "users_per_day": 10.0, "days_revenue": 190.0}],
    }
    return criteo, sims


def test_result_tables_flatten_every_result() -> None:
    criteo, sims = _results()
    t = dashboard.result_tables(criteo, sims)
    est = t["criteo_estimates"].to_pylist()
    assert [r["share_of_naive"] for r in est] == [1.0, 0.75]
    assert t["sim_calibration"].num_rows == 14
    assert {r["lift"] for r in t["sim_calibration"].to_pylist()} == {0.0, 0.1}
    assert t["sim_metric_sensitivity"].to_pylist() == [
        {"rel_mde": 0.1, "metric": "revenue", "days_needed": 190.0}
    ]


def test_build_and_csv_export(tmp_path: Path) -> None:
    ga4, results = tmp_path / "ga4", tmp_path / "results"
    ga4.mkdir()
    results.mkdir()
    for name in dashboard.MART_TABLES:
        pq.write_table(pa.table({"x": [1, 2]}), ga4 / f"{name}.parquet")
    criteo, sims = _results()
    (results / "criteo-readout.json").write_text(json.dumps(criteo))
    (results / "ga4-simulations.json").write_text(json.dumps(sims))
    db = tmp_path / "out" / "ga4.duckdb"
    names = dashboard.build(ga4, results, db)
    assert len(names) == len(dashboard.MART_TABLES) + 7
    assert duckdb.connect(str(db)).execute("SELECT sum(x) FROM mart_daily_kpis").fetchone() == (3,)
    csvs = dashboard.export_csv(db, tmp_path / "csv")
    assert len(csvs) == len(names)
    assert (tmp_path / "csv" / "criteo_estimates.csv").read_text().startswith("outcome,")


def test_cli_dashboard_data_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    ga4 = tmp_path / "data" / "ga4"
    ga4.mkdir(parents=True)
    for name in dashboard.MART_TABLES:
        pq.write_table(pa.table({"x": [1]}), ga4 / f"{name}.parquet")
    results = tmp_path / "docs" / "results"
    results.mkdir(parents=True)
    criteo, sims = _results()
    (results / "criteo-readout.json").write_text(json.dumps(criteo))
    (results / "ga4-simulations.json").write_text(json.dumps(sims))
    cli.main(["dashboard-data"])
    assert (tmp_path / "dashboard" / "sources" / "ga4" / "ga4.duckdb").exists()
    assert len(list((tmp_path / "powerbi" / "data").glob("*.csv"))) == 12
    with pytest.raises(SystemExit):
        cli.main(["no-such-command"])


def test_export_writes_every_mart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from google.cloud import bigquery

    from ablab import export

    class FakeRows:
        def to_arrow(self) -> pa.Table:
            return pa.table({"x": [1, 2, 3]})

    class FakeClient:
        def __init__(self, project: str) -> None:
            self.project = project

        def list_rows(self, table: str) -> FakeRows:
            assert table.startswith("p.ga4_")
            return FakeRows()

    monkeypatch.setattr(bigquery, "Client", FakeClient)
    written = export.export("p", tmp_path)
    assert len(written) == sum(len(t) for t in export.TABLES.values())
    assert all(rows == 3 for _, rows in written)
    assert pq.read_table(tmp_path / "exp_users.parquet").num_rows == 3
