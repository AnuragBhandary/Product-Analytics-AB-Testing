# Dashboard (Evidence)

Six pages of SQL + Markdown over `sources/ga4/ga4.duckdb`, a small file of aggregates built by
`uv run ablab dashboard-data` from the dbt marts and the result JSONs. CI builds the static
site and deploys it to GitHub Pages; no BigQuery credentials are needed.

```bash
npm ci
npm run sources
npm run dev        # http://localhost:3000/Product-Analytics-AB-Testing/
npm run build      # static site in build/
```

Uses the open-source Evidence build (`@evidence-dev/evidence` 40.x); TypeScript is pinned to 5
because Evidence's peer dependencies do not accept 7.
