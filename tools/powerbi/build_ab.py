"""Generate the GA4 / A/B testing Power BI project (PBIP) for Product-Analytics-AB-Testing."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from pbip_lib import (agg, col, csv_partition_m, gradient, indent, lit, meas, measure_tmdl, proj, q,
                      range_filter, short, table_tmdl, topn_filter, visual, write_pbip, write_report,
                      write_semantic_model)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))  # tools/powerbi -> repo root
# Output folder: argv[1], else tools/powerbi/out/ga4-ab-testing. Pass powerbi/ga4-ab-testing only to
# replace the committed (Desktop-saved) project on purpose.
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "out", "ga4-ab-testing")
NAME = "ga4-ab-testing"
# The CSVs are committed in powerbi/data, so the report reads them straight from GitHub: it
# refreshes for anyone who clones the repo, with no local path to set.
DATA = "https://raw.githubusercontent.com/AnuragBhandary/Product-Analytics-AB-Testing/main/powerbi/data"

N = {"sum": "none"}
P = {"sum": "none", "fmt": "0.0%"}
RAW = {"sum": "none", "fmt": "0.000"}

TABLES = {
    "mart_daily_kpis": [
        ("date", "date"), ("users", "int"), ("sessions", "int"), ("engagement_rate", "num", P),
        ("converting_sessions", "int"), ("session_conversion_rate", "num", {"sum": "none", "fmt": "0.00%"}),
        ("purchases", "int"), ("revenue_usd", "cur", {"fmt": "\\$#,0"}), ("average_order_value_usd", "cur", N),
    ],
    "mart_funnel_weekly": [
        ("week", "date"), ("device_category", "text"), ("channel", "text"), ("sessions", "int"),
        *[(f"{k}_{s}", "int") for k in ("open", "closed") for s in
          ("view_item", "add_to_cart", "begin_checkout", "add_shipping_info", "add_payment_info", "purchase")],
    ],
    "mart_channel_performance": [
        ("acquisition_channel", "text"), ("device_category", "text"), ("users", "int"), ("sessions", "int"),
        ("engagement_rate", "num", P), ("converting_sessions", "int"),
        ("session_conversion_rate", "num", {"sum": "none", "fmt": "0.00%"}), ("revenue_usd", "cur"),
        ("revenue_per_session_usd", "cur", N), ("share_sessions_without_session_source", "num", P),
    ],
    "mart_cohort_retention": [
        ("cohort_week", "date"), ("week_number", "int", N), ("cohort_users", "int"), ("active_users", "int"),
        ("retention", "num", P),
    ],
    "mart_product_performance": [
        ("item_name", "text"), ("item_category", "text"), ("item_views", "int"), ("sessions_viewed", "int"),
        ("units_added_to_cart", "int"), ("units_purchased", "int"), ("item_revenue_usd", "cur", {"fmt": "\\$#,0"}),
    ],
    "criteo_estimates": [
        ("outcome", "text"), ("estimator_order", "int", N), ("estimator", "text", {"sortBy": "estimator_order"}),
        ("diff", "num", {"sum": "sum", "fmt": "0.00000"}), ("ci_low", "num", {"sum": "sum", "fmt": "0.00000"}),
        ("ci_high", "num", {"sum": "sum", "fmt": "0.00000"}), ("rel_lift", "num", P),
        ("share_of_naive", "num", {"sum": "none", "fmt": "0%"}),
    ],
    "criteo_segments": [
        ("outcome", "text"), ("segment", "int", N), ("users", "int"), ("mean_score", "num", RAW),
        ("diff", "num", RAW), ("ci_low", "num", RAW), ("ci_high", "num", RAW), ("p_value", "num", RAW),
        ("incremental_outcomes", "num", {"fmt": "#,0"}), ("p_bh", "num", RAW),
        ("share_of_incremental", "num", {"sum": "sum", "fmt": "0%"}),
    ],
    "criteo_balance": [("feature", "text"), ("smd", "num", RAW), ("z", "num", {"sum": "none", "fmt": "0.0"})],
    "sim_calibration": [("lift", "num", {"sum": "none", "fmt": "0%"}), ("analysis", "text"),
                        ("rejection_rate", "num", {"sum": "average", "fmt": "0.0%"})],
    "sim_metric_sensitivity": [("rel_mde", "num", {"sum": "none", "fmt": "0%"}), ("metric", "text"),
                               ("days_needed", "num", {"sum": "none", "fmt": "#,0"})],
    "sim_peeking": [
        ("lift", "num", {"sum": "none", "fmt": "0%"}), ("tau_rel", "num", {"sum": "none", "fmt": "0.00"}),
        ("looks", "int", N), ("reps", "int", N), ("reject_single_final_look", "num", P),
        ("reject_naive_daily_peeking", "num", P), ("reject_msprt_daily_peeking", "num", P),
        ("msprt_median_stop_day", "num", {"sum": "none", "fmt": "0"}),
    ],
    "sim_srm": [
        ("drop_share_of_treatment_bouncers", "num", P), ("users_lost_share", "num", P),
        ("srm_alarm_rate", "num", P), ("false_revenue_win_rate", "num", P),
        ("false_conversion_win_rate", "num", P), ("mean_false_rel_lift_conversion", "num", P),
    ],
}

DESCRIPTIONS = {
    "mart_daily_kpis": "GA4 daily KPIs (dbt mart ga4_marts.mart_daily_kpis).",
    "mart_funnel_weekly": "Weekly e-commerce funnel by device and channel; open and closed funnel counts.",
    "criteo_estimates": "Criteo uplift: naive vs adjusted treatment-effect estimators (analysis output).",
    "sim_peeking": "Simulation: false positives from daily peeking vs a single look vs mSPRT.",
}

FORMATS = {
    "Sessions": "#,0", "Purchases": "#,0", "Revenue": "\\$#,0", "Session Conversion Rate": "0.00%",
    "Average Order Value": "\\$#,0.00", "Revenue per Session": "\\$#,0.00", "Engagement Rate": "0.0%",
    "Revenue Previous Week": "\\$#,0", "Revenue WoW %": "0.0%", "Revenue 7d Rolling": "\\$#,0",
    "Funnel Sessions": "#,0", "View to Cart %": "0.0%", "Cart to Checkout %": "0.0%",
    "Checkout to Purchase %": "0.0%", "Closed Funnel Completion %": "0.00%", "Funnel Step Sessions": "#,0",
    "Funnel Step Drop-off %": "0.0%", "Channel Conversion Rate": "0.00%",
    "Channel Revenue per Session": "\\$#,0.00", "Sessions Without Session Source %": "0.0%",
    "Retention %": "0.0%", "Item Revenue": "\\$#,0", "Units per Viewing Session": "0.0%",
    "Item Revenue Rank": "0", "Naive Lift %": "0.0%", "AIPW Lift %": "0.0%", "AIPW Share of Naive %": "0%",
    "Effect": "0.00000", "Effect CI Low": "0.00000", "Effect CI High": "0.00000",
    "Share of Incremental": "0%", "False Positive Rate": "0.0%", "Users per Arm": "#,0", "Days Needed": "0.0",
    "Selected Item": None,
}
FOLDERS = [("Sessions", "Overview"), ("Funnel Sessions", "Funnel"), ("Channel Conversion Rate", "Channels"),
           ("Retention %", "Retention"), ("Item Revenue", "Products"), ("Naive Lift %", "Experiment"),
           ("Users per Arm", "Sample size")]

PARAMS = [  # name, min, max, step, default, format
    ("Baseline Rate", 0.001, 0.2, 0.001, 0.0137, "0.00%"),
    ("Relative MDE", 0.01, 0.5, 0.01, 0.1, "0%"),
    ("Power", 0.5, 0.95, 0.05, 0.8, "0%"),
    ("Daily Users", 500, 20000, 100, 3159, "#,0"),
]


def parse_measures(path):
    """measures.dax: `Name = expr` (same line or next lines), // comments above, blank-line separated."""
    lines = open(path, encoding="utf-8").read().split("\n")
    out, desc, i = [], [], 0
    head = re.compile(r"^([A-Za-z][A-Za-z0-9 %\-()/]*?) =(.*)$")
    while i < len(lines):
        line = lines[i]
        m = head.match(line)
        if line.startswith("//"):
            text = line[2:].strip()
            if text and not text.startswith("=") and not re.match(r"^(Whole number|Percentage|Currency|Decimal|Text)", text):
                desc.append(text)
            elif re.match(r"^(Whole number|Percentage|Currency|Decimal|Text)\b.*?[.:] ", text):
                desc.append(re.split(r"[.:] ", text, maxsplit=1)[1])
        elif m and not line.startswith(("VAR", "RETURN")):
            name, rest = m.group(1).strip(), m.group(2).strip()
            body = [rest] if rest else []
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].startswith("//"):
                nxt = head.match(lines[i])
                if nxt and not lines[i].startswith(("VAR", "RETURN")) and lines[i][0].isalpha():
                    break
                body.append(lines[i])
                i += 1
            out.append({"name": name, "expr": "\n".join(body), "fmt": FORMATS.get(name, "#,0"),
                        "desc": " ".join(desc) or None})
            desc = []
            continue
        elif not line.strip():
            desc = []
        i += 1
    folder = "Overview"
    starts = dict(FOLDERS)
    for m in out:
        folder = starts.get(m["name"], folder)
        m["folder"] = folder
    return out


def raw_tables():
    date = """/// Calendar for the GA4 export window (from the first funnel week). Marked as the date table.
table Date
\tdataCategory: Time

\tcolumn Date
\t\tdataType: dateTime
\t\tisKey
\t\tformatString: yyyy-mm-dd
\t\tsummarizeBy: none
\t\tisNameInferred
\t\tsourceColumn: [Date]

\tcolumn Week = 'Date'[Date] - WEEKDAY ( 'Date'[Date], 3 )
\t\tdataType: dateTime
\t\tformatString: yyyy-mm-dd
\t\tsummarizeBy: none

\tcolumn Month = FORMAT ( 'Date'[Date], "yyyy-mm" )
\t\tdataType: string
\t\tsummarizeBy: none

\tpartition Date = calculated
\t\tmode: import
\t\tsource = CALENDAR ( DATE ( 2020, 10, 26 ), DATE ( 2021, 1, 31 ) )
"""
    funnel = """/// Funnel steps in order; Funnel Step Sessions switches on [Order].
table FunnelStep

\tcolumn Order
\t\tdataType: int64
\t\tformatString: 0
\t\tsummarizeBy: none
\t\tsourceColumn: Order

\tcolumn Step
\t\tdataType: string
\t\tsummarizeBy: none
\t\tsourceColumn: Step
\t\tsortByColumn: Order

\tpartition FunnelStep = m
\t\tmode: import
\t\tsource =
\t\t\t\t#table(
\t\t\t\t    type table [Order = Int64.Type, Step = text],
\t\t\t\t    {{1, "View item"}, {2, "Add to cart"}, {3, "Begin checkout"}, {4, "Shipping info"}, {5, "Payment info"}, {6, "Purchase"}}
\t\t\t\t)
"""
    outcome = """/// Outcome dimension (visit, conversion): one slicer filters both Criteo tables.
table Outcome

\tcolumn outcome
\t\tdataType: string
\t\tsummarizeBy: none
\t\tsourceColumn: outcome

\tpartition Outcome = m
\t\tmode: import
\t\tsource = #table(type table [outcome = text], {{"visit"}, {"conversion"}})
"""
    tables = [("Date", date), ("FunnelStep", funnel), ("Outcome", outcome)]
    for name, lo, hi, step, default, fmt in PARAMS:
        tables.append((name, f"""/// What-if parameter for the sample-size calculator.
table {q(name)}

\tmeasure {q(name + ' Value')} = SELECTEDVALUE ( {q(name)}[{name}], {default} )
\t\tformatString: {fmt}

\tcolumn {q(name)}
\t\tdataType: double
\t\tformatString: {fmt}
\t\tsummarizeBy: none
\t\tsourceColumn: [Value]

\t\textendedProperty ParameterMetadata =
\t\t\t\t{{
\t\t\t\t  "version": 0
\t\t\t\t}}

\tpartition {q(name)} = calculated
\t\tmode: import
\t\tsource = GENERATESERIES ( {lo}, {hi}, {step} )
"""))
    return tables


def build_model():
    tables = []
    for t, cols in TABLES.items():
        m = csv_partition_m(f"{t}.csv", cols, "DataFolder", nulls=("", "nan"), web=True)
        tables.append((t, table_tmdl(t, cols, m, description=DESCRIPTIONS.get(t))))
    measures = parse_measures(os.path.join(REPO, "powerbi", "measures.dax"))
    mt = table_tmdl("_Measures", [("Dummy", "text", {"hidden": True})], "#table(type table [Dummy = text], {})",
                    description="Measure table: every DAX measure lives here (see powerbi/measures.dax).",
                    measures=measures)
    tables = [("_Measures", mt)] + raw_tables() + tables
    rels = [
        ("mart_daily_kpis.date", "Date.Date", {}),
        ("mart_funnel_weekly.week", "Date.Date", {}),
        ("criteo_estimates.outcome", "Outcome.outcome", {}),
        ("criteo_segments.outcome", "Outcome.outcome", {}),
    ]
    expressions = [
        "/// Base URL of the CSVs (powerbi/data on GitHub). Change it in Transform data > Edit parameters.",
        f'expression DataFolder = "{DATA}" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]',
        "\tannotation PBI_ResultType = Text",
        "",
    ]
    order = ["DataFolder", "_Measures", "FunnelStep", "Outcome"] + list(TABLES)
    write_semantic_model(ROOT, NAME, tables, rels, [], expressions, order)
    return measures


def cards(page, names, x0, y, w, h, gap=10):
    return [visual(f"{page}Card{i}", "card", (x0 + i * (w + gap), y, w, h), {"Values": [meas(n)]})
            for i, n in enumerate(names)]


def slicer(name, pos, entity, column, title, mode="Dropdown", single=False, default=None):
    objects = {"data": [{"properties": {"mode": lit(mode)}}], "header": [{"properties": {"show": lit(False)}}]}
    if single:
        objects["selection"] = [{"properties": {"singleSelect": lit(True)}}]
    if default is not None:
        ref = {"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": column}}
        objects["general"] = [{"properties": {"filter": {"filter": {
            "Version": 2, "From": [{"Name": "s", "Entity": entity, "Type": 0}],
            "Where": [{"Condition": {"In": {"Expressions": [ref],
                                            "Values": [[{"Literal": {"Value": f"'{default}'"}}]]}}}]}}}}]
    return visual(name, "slicer", pos, {"Values": [col(entity, column)]}, title=title, objects=objects)


def textbox(name, pos, text):
    return visual(name, "textbox", pos, objects={"general": [{"properties": {"paragraphs": [
        {"textRuns": [{"value": text, "textStyle": {"fontSize": "10pt", "fontStyle": "italic"}}]}]}}]})


FULL = {"labels": [{"properties": {"labelDisplayUnits": {"expr": {"Literal": {"Value": "1D"}}}}}]}


def build_report():
    date = col("Date", "Date")
    ch = "mart_channel_performance"
    conv = meas("Channel Conversion Rate")
    ov = [
        *cards("ov", ["Sessions", "Purchases", "Revenue", "Session Conversion Rate", "Average Order Value"],
               20, 10, 240, 100),
        visual("ovRevenue", "lineChart", (20, 120, 620, 420), {"Category": [date],
               "Y": [meas("Revenue"), meas("Revenue 7d Rolling")]},
               title="Daily revenue and 7-day rolling revenue", sort=[(date, "Ascending")],
               filters=[range_filter("ovDates", "Date", "Date", [(">=", "datetime'2020-11-01T00:00:00'")])]),
        visual("ovChannels", "tableEx", (650, 200, 610, 340),
               {"Values": [col(ch, "acquisition_channel"), conv, meas("Channel Revenue per Session"),
                           meas("Sessions Without Session Source %")]},
               title="Channels (user acquisition channel)", sort=[(conv, "Descending")],
               objects={"values": [gradient(conv, "_Measures.Channel Conversion Rate", ["#FFFFFF", "#2E86C1"])]}),
        slicer("ovDevice", (650, 120, 300, 70), ch, "device_category", "Device (channels table)"),
        textbox("ovNote", (20, 560, 1240, 60),
                "26% of sessions have no session-level source (mostly one-page bounces); channels use the "
                "user's acquisition channel."),
    ]

    step = col("FunnelStep", "Step")
    fw = "mart_funnel_weekly"
    fu = [
        visual("fuFunnel", "funnel", (20, 20, 620, 400), {"Category": [step], "Y": [meas("Funnel Step Sessions")]},
               title="Closed funnel: sessions completing each step in order", sort=[(step, "Ascending")]),
        visual("fuDrop", "clusteredColumnChart", (650, 20, 610, 400),
               {"Category": [step], "Y": [meas("Funnel Step Drop-off %")]},
               title="Drop-off at each step vs the previous one", sort=[(step, "Ascending")],
               objects={"labels": [{"properties": {"show": lit(True)}}]}),
        visual("fuDevice", "pivotTable", (20, 430, 620, 270),
               {"Rows": [col(fw, "device_category")],
                "Values": [meas("View to Cart %"), meas("Cart to Checkout %"), meas("Checkout to Purchase %")]},
               title="Open-funnel step rates by device"),
        slicer("fuChannel", (650, 430, 300, 70), fw, "channel", "Channel"),
        slicer("fuDeviceSl", (960, 430, 300, 70), fw, "device_category", "Device"),
        visual("fuCompletion", "card", (650, 520, 610, 120), {"Values": [meas("Closed Funnel Completion %")]}),
    ]

    cr = "mart_cohort_retention"
    ret = meas("Retention %")
    wk = col(cr, "week_number")
    re_ = [
        visual("reMatrix", "pivotTable", (20, 20, 860, 540),
               {"Rows": [col(cr, "cohort_week")], "Columns": [wk], "Values": [ret]},
               title="Weekly cohort retention: share of each cohort active N weeks later (week 0 = 100%, hidden)",
               filters=[range_filter("reMatrixWeeks", cr, "week_number", [(">=", "1L"), ("<=", "12L")])],
               objects={"values": [gradient(ret, "_Measures.Retention %", ["#FFFFFF", "#1F4E79"])],
                        "subTotals": [{"properties": {"columnSubtotals": lit(False)}}]}),
        visual("reCurve", "lineChart", (890, 20, 370, 540), {"Category": [wk], "Y": [ret]},
               title="Retention curve (weeks 1-12, pooled)", sort=[(wk, "Ascending")],
               filters=[range_filter("reWeeks", cr, "week_number", [(">=", "1L"), ("<=", "12L")])]),
        textbox("reNote", (20, 570, 1240, 60),
                "Right-censoring: later cohorts have fewer observable weeks (the export ends 2021-01-31), so "
                "their rows stop early. Pooled retention sums active users over cohort users, never an "
                "average of cohort percentages."),
    ]

    pp = "mart_product_performance"
    item = col(pp, "item_name")
    pr = [
        visual("prTop", "clusteredBarChart", (20, 20, 560, 680), {"Category": [item], "Y": [meas("Item Revenue")]},
               title="Top 15 items by revenue (right-click > Drill through > Item detail)",
               sort=[(meas("Item Revenue"), "Descending")],
               filters=[topn_filter("prTop15", pp, "item_name", "Item Revenue", 15)]),
        visual("prTable", "tableEx", (590, 20, 670, 680),
               {"Values": [item, col(pp, "item_category"), proj(agg(pp, "item_views"), "Views"),
                           proj(agg(pp, "sessions_viewed"), "Sessions viewed"),
                           proj(agg(pp, "units_purchased"), "Units purchased"), meas("Item Revenue"),
                           meas("Units per Viewing Session")]},
               title="All items", sort=[(meas("Item Revenue"), "Descending")]),
    ]

    idt = [
        visual("idBack", "actionButton", (20, 20, 40, 40),
               objects={"icon": [{"properties": {"shapeType": lit("back")}, "selector": {"id": "default"}}]},
               vco={"visualLink": [{"properties": {"show": lit(True), "type": lit("Back")}}]}),
        visual("idHeader", "card", (70, 10, 1190, 70), {"Values": [meas("Selected Item")]},
               objects={"categoryLabels": [{"properties": {"show": lit(False)}}]}),
        *[visual(f"idCard{i}", "card", (20 + (i % 4) * 310, 100 + (i // 4) * 130, 300, 120), {"Values": [f]})
          for i, f in enumerate([proj(agg(pp, "item_views"), "Views"), proj(agg(pp, "sessions_viewed"), "Sessions viewed"),
                                 proj(agg(pp, "units_purchased"), "Units purchased"), meas("Item Revenue"),
                                 meas("Units per Viewing Session"), meas("Item Revenue Rank")])],
    ]

    est = "criteo_estimates"
    seg = "criteo_segments"
    estimator = col(est, "estimator")
    ex = [
        slicer("exOutcome", (20, 10, 190, 90), "Outcome", "outcome", "Outcome", mode="Basic", single=True,
               default="visit"),
        *cards("ex", ["Naive Lift %", "AIPW Lift %", "AIPW Share of Naive %"], 220, 10, 205, 90),
        visual("exEstimates", "clusteredBarChart", (20, 110, 420, 250),
               {"Category": [estimator], "Y": [meas("Effect")],
                "Tooltips": [meas("Effect CI Low"), meas("Effect CI High")]},
               title="Treatment effect by estimator (95% CI in tooltip)", sort=[(estimator, "Ascending")],
               objects={"labels": [{"properties": {"show": lit(True)}}]}),
        visual("exSegments", "clusteredColumnChart", (450, 110, 410, 250),
               {"Category": [col(seg, "segment")], "Y": [meas("Share of Incremental")]},
               title="Share of incremental outcomes by uplift-score decile",
               sort=[(col(seg, "segment"), "Ascending")]),
        visual("exPeeking", "tableEx", (20, 370, 560, 160),
               {"Values": [proj(col("sim_peeking", c), d) for c, d in (
                   ("lift", "True lift"), ("tau_rel", "mSPRT tau"), ("reject_single_final_look", "Single look"),
                   ("reject_naive_daily_peeking", "Naive daily peeking"),
                   ("reject_msprt_daily_peeking", "mSPRT daily"), ("msprt_median_stop_day", "mSPRT median stop day"))]},
               title="Peeking: rejection rate by analysis (lift 0 = false positives)"),
        visual("exSrm", "tableEx", (20, 540, 560, 170),
               {"Values": [proj(col("sim_srm", c), d) for c, d in (
                   ("drop_share_of_treatment_bouncers", "Treatment bouncers lost"),
                   ("users_lost_share", "Users lost"), ("srm_alarm_rate", "SRM alarm rate"),
                   ("false_revenue_win_rate", "False revenue win"),
                   ("false_conversion_win_rate", "False conversion win"))]},
               title="Sample-ratio mismatch: losing treatment bouncers fakes a win"),
        visual("exCalibration", "pivotTable", (590, 410, 670, 300),
               {"Rows": [col("sim_calibration", "analysis")], "Columns": [col("sim_calibration", "lift")],
                "Values": [proj(agg("sim_calibration", "rejection_rate", 1), "Rejection rate")]},
               title="Calibration: rejection rate by true lift (lift 0 = false positive rate, target 5%)",
               objects={"subTotals": [{"properties": {"rowSubtotals": lit(False), "columnSubtotals": lit(False)}}]}),
        *[slicer(f"exParam{i}", (870, 10 + i * 75, 390, 70), name, name, f"{name} (default {default})",
                 single=True)
          for i, (name, _lo, _hi, _step, default, _fmt) in enumerate(PARAMS)],
        visual("exUsers", "card", (870, 310, 190, 90), {"Values": [meas("Users per Arm")]}, objects=FULL),
        visual("exDays", "card", (1070, 310, 190, 90), {"Values": [meas("Days Needed")]}, objects=FULL),
    ]

    item_drill = col(pp, "item_name")
    pages = [
        {"name": "overview", "displayName": "Overview", "visuals": ov},
        {"name": "funnel", "displayName": "Funnel", "visuals": fu},
        {"name": "retention", "displayName": "Retention", "visuals": re_},
        {"name": "products", "displayName": "Products", "visuals": pr},
        {"name": "experiment", "displayName": "Experiment", "visuals": ex},
        {"name": "itemdetail", "displayName": "Item detail", "visuals": idt, "visibility": "HiddenInViewMode",
         "filters": [{"name": "idDrillItem", "field": item_drill, "type": "Categorical", "howCreated": "Drillthrough"}],
         "binding": {"name": short("item-drill"), "type": "Drillthrough",
                     "parameters": [{"name": short("item-param"), "boundFilter": "idDrillItem",
                                     "fieldExpr": item_drill}]}},
    ]
    write_report(ROOT, NAME, pages)


if __name__ == "__main__":
    ms = build_model()
    build_report()
    write_pbip(ROOT, NAME)
    print(f"{len(ms)} measures:")
    for m in ms:
        print(f"  [{m['folder']}] {m['name']}  fmt={m['fmt']}  lines={len(m['expr'].splitlines())}")
