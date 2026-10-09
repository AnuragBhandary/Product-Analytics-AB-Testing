"""ablab command line: data download, the Criteo readout, GA4 export and simulations."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

CRITEO_URL = (
    "https://huggingface.co/datasets/criteo/criteo-uplift/resolve/main/"
    "criteo-research-uplift-v2.1.csv.gz"
)
DATA = Path("data")
RESULTS = Path("docs/results")


def _write(name: str, payload: dict[str, Any]) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / name
    path.write_text(json.dumps(payload, indent=2))
    return path


def cmd_criteo_data(_: argparse.Namespace) -> None:
    from ablab import criteo

    raw = DATA / "raw" / "criteo-research-uplift-v2.1.csv.gz"
    raw.parent.mkdir(parents=True, exist_ok=True)
    if not raw.exists():
        print(f"downloading {CRITEO_URL} (311 MB)")
        urllib.request.urlretrieve(CRITEO_URL, raw)
    criteo.to_parquet(raw, DATA / "criteo.parquet")
    print(f"wrote {DATA / 'criteo.parquet'}")


def cmd_criteo(args: argparse.Namespace) -> None:
    from ablab import criteo

    t = time.time()
    result = criteo.readout(DATA / "criteo.parquet", threads=args.threads)
    result["seconds"] = round(time.time() - t, 1)
    print(f"wrote {_write('criteo-readout.json', result)} in {result['seconds']} s")


def cmd_export(args: argparse.Namespace) -> None:
    from ablab.export import export

    for table, rows in export(args.project, DATA / "ga4"):
        print(f"{table}: {rows:,} rows")


def cmd_simulate(args: argparse.Namespace) -> None:
    from ablab import simulate

    t = time.time()
    u = simulate.load_users(
        DATA / "ga4" / "exp_users.parquet", DATA / "ga4" / "exp_user_days.parquet"
    )
    result: dict[str, Any] = {
        "users": u.n,
        "days": u.days,
        "purchaser_rate": float(u.purchaser.mean()),
        "revenue_per_user": float(u.revenue.mean()),
        "returning_share": float((u.pre_sessions > 0).mean()),
        "metric_sensitivity": [simulate.required_days(u, m) for m in (0.05, 0.10)],
        "calibration": simulate.calibration(u, [0.0], reps=args.reps * 2, seed=args.seed)
        | simulate.calibration(u, [0.1, 0.25], reps=args.reps, seed=args.seed + 1),
        "peeking": [
            simulate.peeking(u, args.reps, lift, tau, seed=args.seed + 2)
            for lift in (0.0, 0.25)
            for tau in (0.05, 0.25)
        ],
        "srm": [
            simulate.srm_detection(u, share, reps=args.reps // 2, seed=args.seed + 3)
            for share in (0.01, 0.02, 0.05, 0.10)
        ],
    }
    result["seconds"] = round(time.time() - t, 1)
    print(f"wrote {_write('ga4-simulations.json', result)} in {result['seconds']} s")


def cmd_dashboard_data(_: argparse.Namespace) -> None:
    from ablab import dashboard

    db = Path("dashboard/sources/ga4/ga4.duckdb")
    tables = dashboard.build(DATA / "ga4", RESULTS, db)
    csvs = dashboard.export_csv(db, Path("powerbi/data"))
    print(f"wrote {db} ({len(tables)} tables) and {len(csvs)} CSVs in powerbi/data")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ablab")
    sub = parser.add_subparsers(required=True)
    p = sub.add_parser("criteo-data", help="download Criteo uplift v2.1 and convert to Parquet")
    p.set_defaults(func=cmd_criteo_data)
    p = sub.add_parser("criteo", help="experiment readout on 14M users -> docs/results")
    p.add_argument("--threads", type=int, default=4)
    p.set_defaults(func=cmd_criteo)
    p = sub.add_parser("export", help="BigQuery marts -> data/ga4/*.parquet")
    p.add_argument("--project", required=True, help="GCP project holding the dbt datasets")
    p.set_defaults(func=cmd_export)
    p = sub.add_parser("simulate", help="A/A, power, peeking and SRM simulations on GA4 users")
    p.add_argument("--reps", type=int, default=1000)
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(func=cmd_simulate)
    p = sub.add_parser("dashboard-data", help="results + marts -> Evidence DuckDB + Power BI CSVs")
    p.set_defaults(func=cmd_dashboard_data)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
