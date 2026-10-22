# Report-as-code tooling (Power BI project)

These scripts produced the first version of
[`powerbi/ga4-ab-testing`](../../powerbi/ga4-ab-testing). After review, the project was opened,
refreshed, tested and re-saved in Power BI Desktop. **The committed, Desktop-saved files are the
version of record.** Edit the report in Desktop. Use these scripts to see how the project is put
together, or to regenerate it from scratch.

| File | What it does |
|---|---|
| `pbip_lib.py` | Writes a Power BI project (`.pbip`): the semantic model as TMDL and the report as PBIR JSON. Helpers for M queries (local folder or URL), measures, visuals, filters and conditional formatting. |
| `build_ab.py` | The GA4 / A/B spec: 12 CSV tables, the `Date`, `FunnelStep` and `Outcome` tables, 4 what-if parameters for the sample-size calculator, and 5 pages plus a hidden drill-through. Measures are read from [`powerbi/measures.dax`](../../powerbi/measures.dax). |
| `validate_pbir.py` | Validates every JSON file against the Microsoft schema named in its `$schema`, following cross-file `$ref`s (fetched from github.com/microsoft/json-schemas and cached). |

```bash
pip install jsonschema referencing
python tools/powerbi/build_ab.py                        # writes tools/powerbi/out/ga4-ab-testing (gitignored)
python tools/powerbi/validate_pbir.py tools/powerbi/out/ga4-ab-testing
```

The build script writes to `tools/powerbi/out/` unless you give an output path, so the committed
project isn't overwritten by accident.

**Data source:** the report reads the CSVs in [`powerbi/data`](../../powerbi/data) straight from
GitHub (`DataFolder` = the raw.githubusercontent.com URL of that folder, read with
`Web.Contents(DataFolder, [RelativePath = "<file>.csv"])`). A fresh clone refreshes with no
local path to set. Power BI asks once how to access the web content: choose **Anonymous**.
