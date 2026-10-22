# Results

Every number here is reproducible with the Makefile targets named in each section. Raw outputs:
[`results/criteo-readout.json`](results/criteo-readout.json),
[`results/ga4-simulations.json`](results/ga4-simulations.json). Hardware: Apple-silicon
laptop, computations capped at 4 threads.

## 1. GA4 data model (`make dbt`)

Source: `bigquery-public-data.ga4_obfuscated_sample_ecommerce`, 1 Nov 2020 to 31 Jan 2021.

| | |
|---|---|
| Raw events | 4,295,584 (92 daily tables) |
| Models | 13 (2 staging, 1 intermediate, 8 marts, 2 experiment) |
| Data tests | 27 (generic + 6 singular), all passing; 40 dbt nodes in total |
| Build time | about 60 s in the BigQuery sandbox; 4.7 GB scanned by the models per full build (free tier: 1 TB a month) |
| Sessions | 360,129 (equals distinct user + ga_session_id in the raw export) |
| Users | 270,154 |
| Purchases | 4,922 after deduplication, from 5,692 purchase events |
| Revenue | $340,647, identical (to the cent) across an independent raw dedup, `fct_purchases` and `fct_sessions` |

Data problems found and handled (details in [DESIGN.md](DESIGN.md#data-quality)):

| Problem | Count | Handling |
|---|---|---|
| Purchase logged more than once (same id, user, revenue) | 314 purchases | keep the first event |
| Same transaction id on two different users | 15 ids | key = id + user |
| transaction_id `(not set)` or null | 906 events (450 with $0) | each non-zero event is one purchase |
| Session has no session-level source on any event | 94,554 sessions (26%) | explicit "Unknown" session channel; channel reporting uses first-touch acquisition channel |
| Sandbox deletes partitions older than 60 days | every partition | no date partitioning; volume test added |

## 2. Product analytics (`dashboard/`)

| | |
|---|---|
| Session conversion | 1.23% (4,446 converting sessions) |
| Average order value | $69.21 |
| Closed funnel | view item 77,020 → cart 15,173 → checkout 5,959 → shipping 5,959 → payment 3,858 → purchase 2,573 |
| Open funnel purchases | 4,446; 1,873 of them (42%) had no add-to-cart in the same session (cart filled in an earlier session), so the session-scoped closed funnel undercounts |
| Checkout → purchase | desktop 39.6%, mobile 40.7%, tablet 37.9% |
| Week-1 retention | 4.2% pooled; under 1% from week 5 |
| Best channel (revenue / session) | Referral $1.24; Organic Search $0.80; Paid Search $0.54 |
| Top item by revenue | Google Zip Hoodie F/C, $13,152 from 260 units |

If the 26% of sessions without a session source were dropped instead of kept as "Unknown",
every channel's conversion rate would rise by about 36% (1.23% → 1.67% overall), because
those sessions are mostly one-page bounces (1.5 page views, 11 s engaged vs 4.6 and 91 s).

## 3. Criteo incrementality test (`make criteo`, 47 s)

13,979,592 users; 11,882,655 treatment, 2,096,937 control; 3.6% of treatment users were
actually exposed to an ad; no control user was.

### Split and balance

| Check | Result |
|---|---|
| SRM vs designed 85/15 | 85.00001% treatment, p = 0.999: passes |
| Feature balance | 9 of 12 features more than 10 standard errors apart (worst: f3, SMD −0.047, z = −63) |
| Predict assignment from features (cross-fitted, out of fold) | AUC 0.509, 42 standard errors above 0.5 |
| Estimated propensity, 1st to 99th percentile | 0.843 to 0.894 (design: 0.85 for everyone) |

The file pools several incrementality tests that were subsampled (as its documentation says),
so assignment depends on features. An SRM check cannot catch this because the pooled ratio is
exact.

### Effect estimates

| Visit (control rate 3.82%) | Effect | 95% CI | Relative lift | vs naive |
|---|---|---|---|---|
| Difference in means (naive) | +1.034 pp | 1.006 to 1.063 | +27.1% | 100% |
| CUPAC (CUPED on a cross-fitted baseline prediction) | +0.734 pp | 0.710 to 0.758 | +19.2% | 71% |
| Propensity-stratified (20 strata) | +0.783 pp | 0.755 to 0.812 | +20.5% | 76% |
| Inverse propensity weighting | +0.754 pp | 0.723 to 0.784 | +19.7% | 73% |
| **AIPW (doubly robust)** | **+0.746 pp** | 0.721 to 0.771 | **+19.5%** | 72% |

| Conversion (control rate 0.194%) | Effect | 95% CI | Relative lift | vs naive |
|---|---|---|---|---|
| Difference in means (naive) | +0.1152 pp | 0.1085 to 0.1219 | +59.4% | 100% |
| CUPAC | +0.1112 pp | 0.1046 to 0.1177 | +57.4% | 97% |
| Propensity-stratified | +0.0931 pp | 0.0859 to 0.1003 | +48.1% | 81% |
| Inverse propensity weighting | +0.0902 pp | 0.0828 to 0.0976 | +46.6% | 78% |
| **AIPW (doubly robust)** | **+0.1004 pp** | 0.0929 to 0.1079 | **+51.8%** | 87% |

- CUPAC removed 32% of the variance of the visit metric and 5% for conversion.
- Effect on exposed users (doubly robust complier effect): an ad exposure caused a visit for
  21.2% of exposed users (95% CI 20.4% to 21.9%) and a conversion for 2.8% (2.6% to 3.1%).
- Caveat: adjustment removes imbalance in observed features only. The adjusted estimators
  agreeing with each other is evidence, not proof, that nothing unobserved remains.

### Who responds (deciles of predicted baseline visit rate, AIPW, BH-adjusted)

| Decile | Share of incremental visits | Share of incremental conversions |
|---|---|---|
| 1 to 7 | 6.2% | 8.1% |
| 8 | 7.1% | 2.9% |
| 9 | 24.2% | 7.4% |
| 10 | **62.6%** | **81.6%** |

All deciles but one (decile 2, both outcomes) are significant after Benjamini-Hochberg.

### Validating the test machinery on this data

| Check | Predicted | Observed |
|---|---|---|
| Power, visit, 20,000 users (1,000 subsampled experiments) | 76.2% | 76.9% |
| Power, visit, 50,000 users | 98.8% | 98.1% |
| Power, conversion, 100,000 users (500 experiments) | 80.9% | 81.0% |
| Power, conversion, 200,000 users | 98.0% | 97.2% |
| A/A false positives, visit, 100,000 users (1,000 splits of control) | 5% | 4.5% |
| A/A false positives, conversion, 1,000,000 users (500 splits) | 5% | 5.0% |

Planning: detecting a 10% relative lift in a 0.194% conversion rate at 80% power needs about
1.70M users at 50/50, or 3.22M at Criteo's 85/15 split (the unequal split costs 90% more users).

## 4. Testing the tests on GA4 users (`make simulate`, 90 s)

195,884 users who visited between 1 Dec 2020 and 31 Jan 2021, each "assigned" at their first
session in that window; outcomes over the window. Purchaser rate 1.37%; revenue per user $1.10
with a standard deviation of $15.23 (coefficient of variation 13.8). Only 2.6% had any
November (pre-period) activity.

### Calibration and power (A/A: 2,000 experiments; lifts: 1,000 each)

| Analysis | A/A rejection | Power at +10% | Power at +25% |
|---|---|---|---|
| Purchaser rate, z-test | 4.1% | 72.5% | 100% |
| Revenue per user, Welch | 4.9% | 34.1% | 96.6% |
| Revenue capped at p99 of purchases | 5.1% | **41.5%** | 99.6% |
| Revenue, CUPED (pre-period revenue) | 5.3% | 34.3% | 96.6% |
| Revenue, CUPAC (model on device, country, channel, pre-period) | 5.0% | 33.6% | 96.8% |
| Session conversion rate, delta method | 4.6% | 64.9% | 100% |
| Session conversion rate, naive binomial | 5.7% | 68.5% | 100% |

- Revenue CIs covered the true lift in 94.95%, 95.1% and 94.6% of experiments.
- CUPED removed 0.24% of revenue variance and CUPAC 0.60%: with 97% of users new, there is no
  pre-period signal to use.
- The naive per-session test rejected 5.7% vs 4.6% for the delta method: in the direction
  theory predicts (a user's sessions are correlated), but within the noise of 2,000 runs,
  because 84% of these users have exactly one session. The delta method matters when users
  have many sessions; here it is cheap insurance.

### Which metric to power on (80% power, 50/50, 3,159 users a day)

| Metric | CV | Days for +5% | Days for +10% |
|---|---|---|---|
| Revenue per user | 13.8 | 759 | 190 |
| Revenue per user, CUPAC | 13.8 | 754 | 189 |
| Revenue capped at p99 | 12.2 | 590 | 147 |
| Purchaser rate | 8.5 | 286 | 72 |
| **Add-to-cart rate** | 4.2 | **69** | **17** |

### Peeking (1,000 experiments each, 62 daily looks)

| True lift | mSPRT tuned for | One look at day 62 | Naive p, daily | mSPRT, daily | mSPRT median stop |
|---|---|---|---|---|---|
| 0 | 5% | 5.3% | **29.7%** | 0.0% | |
| 0 | 25% | 5.3% | 29.7% | **1.5%** | |
| +25% | 5% | 93.4% | 96.7% | 17.5% | day 55 |
| +25% | 25% | 93.4% | 96.7% | **73.4%** | **day 18** |

### Broken randomisation: a bug loses some treatment users who bounce (500 experiments each)

| Treatment users lost | SRM alarm (p < 0.001) | False conversion "win" (p < 0.05) | Fake conversion lift |
|---|---|---|---|
| 0.4% | 7.6% | 5.6% | +0.9% |
| 0.8% | 61.6% | 6.8% | +1.7% |
| 2.0% | **100%** | 20.0% | +4.3% |
| 4.1% | 100% | 58.0% | +9.0% |

## 5. Engineering

| | |
|---|---|
| Python tests | 33, 93% line + branch coverage (stats against scipy and hand-computed values; simulations; estimators on synthetic confounded data) |
| CI | ruff, mypy --strict, sqlfluff (BigQuery dialect), dbt parse, pytest, Evidence strict build, GitHub Pages deploy |
| Dashboard | Evidence, 6 pages, built from a committed 3.6 MB DuckDB of aggregates |
| Power BI | 5-page report + hidden drill-through, 35 DAX measures, what-if sample-size calculator: `powerbi/ga4-ab-testing` (.pbip), [PDF](../powerbi/ga4-ab-testing.pdf) |
