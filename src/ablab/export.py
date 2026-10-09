"""Pull the dbt marts out of BigQuery into Parquet for the simulations and dashboards.

The marts are small (the largest is 360k sessions); everything heavy already ran in BigQuery.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

TABLES = {
    "ga4_marts": [
        "fct_sessions",
        "fct_purchases",
        "dim_users",
        "mart_funnel_weekly",
        "mart_cohort_retention",
        "mart_daily_kpis",
        "mart_channel_performance",
        "mart_product_performance",
    ],
    "ga4_experiment": ["exp_users", "exp_user_days"],
}


def export(project: str, out_dir: Path) -> list[tuple[str, int]]:
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for dataset, tables in TABLES.items():
        for table in tables:
            arrow = client.list_rows(f"{project}.{dataset}.{table}").to_arrow()
            pq.write_table(arrow, out_dir / f"{table}.parquet")
            written.append((table, arrow.num_rows))
    return written
