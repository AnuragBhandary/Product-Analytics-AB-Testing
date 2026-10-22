# Design

Why each piece is the way it is. Numbers are in [RESULTS.md](RESULTS.md).

## Scope: two datasets, because each lacks what the other has

- **GA4 sample** (Google Merchandise Store) has real product behaviour: sessions, funnels,
  retention, skewed revenue. It has no experiment.
- **Criteo uplift v2.1** is a real randomised experiment at scale (14M users). It has no
  product behaviour, and only binary outcomes.

So the product analytics and the "is my test machinery calibrated?" work run on GA4 users (with
simulated assignment, so the truth is known), and the real readout runs on Criteo.

## Warehouse: BigQuery sandbox + dbt

- The GA4 sample only exists in BigQuery, and analysts query GA4 exports there, so the models
  are BigQuery SQL (`UNNEST(event_params)`, `_TABLE_SUFFIX`, `QUALIFY`, `ARRAY_AGG ... LIMIT 1`).
- The sandbox is free with no card, with limits that shaped the design:
  - **No DML**, so every model is `CREATE OR REPLACE TABLE` (dbt `table`); no incremental
    models. Fine at 4.3M events: a full build is about 60 s.
  - **Partitions expire 60 days after their partition date.** The first build partitioned
    `stg_ga4__events` and `fct_sessions` by date; the data is from 2020, so BigQuery deleted
    every partition on write. Every model was empty, and every test passed (see below). The
    tables are now clustered only.
  - **Tables expire 60 days after creation.** `make dbt` rebuilds everything in a minute;
    Power BI uses Import mode so a saved report keeps its data.
- Layers: `staging` (flatten events and items) → `intermediate` (deduplicated purchases) →
  `marts` (sessions, users, purchases, funnel, cohorts, channels, products, daily KPIs) →
  `experiment` (one row per user for simulations, plus a user-day table for peeking).

## Data quality

| Issue | Decision | Why |
|---|---|---|
| 314 purchases logged more than once with the same id, user and revenue | keep the first event per (id, user) | duplicate hits (e.g. a reloaded confirmation page); counting them would add $21,518, 6.3% of revenue |
| 15 transaction ids shared by two users with different revenue | key is id + user | the obfuscation reuses ids; merging them would drop real purchases |
| 906 purchase events with id `(not set)` or null | each event with revenue > 0 is a purchase; $0 ones dropped | cannot deduplicate what has no id; $0 rows are not purchases |
| Session source present on only some events; 26% of sessions have none | keep "Unknown" for the session channel; report channels by first-touch acquisition channel | dropping the Unknown sessions (mostly bounces) would inflate conversion by about 36% |
| Obfuscated values (`<Other>`, `(data deleted)`) | separate channel groups | guessing would invent attribution |

## Tests that cannot pass vacuously

After the partition incident the suite was hardened, because the original tests could not
fail on empty input:

- `assert_revenue_reconciles` compares an **independent** dedup written straight against the
  public source (distinct id + user + revenue) with `fct_purchases` and `fct_sessions`. It now
  fails on NULLs, so an empty model fails instead of comparing NULL to NULL.
- `assert_sessions_reconcile_to_raw` fails if the raw count is 0.
- `assert_models_have_expected_volume` bounds every key model's row count from profiling the
  raw export (events must equal 4,295,584 exactly).
- `assert_closed_funnel_never_increases`, `assert_cohort_week_zero_is_full`,
  `assert_experiment_revenue_reconciles`, plus unique / not_null / relationships /
  accepted_values on keys and channels.

## Funnel definition

Two funnels, both in the mart: **open** (did the step at all) and **closed** (did the step and
every earlier one, in any order, within the session). Order within a session is not enforced
because GA4 event timestamps inside a page load are not reliable enough to order checkout
steps. The closed funnel is monotone by construction, and a test checks it. 1,873 of the 4,446
converting sessions (42%) have no add-to-cart event in the same session: the cart was filled in
an earlier session and persisted. A session-scoped closed funnel therefore undercounts
purchases; the dashboard shows both, and a user-scoped funnel is the natural next step.

## Retention

ISO-week cohorts by first visit, activity = any session. The sample starts on a Sunday, so the
first ISO week (one day) is excluded. Later cohorts have fewer observable weeks; the curve
pools only cohorts where a week is observable (right-censoring is not churn).

## Experiment statistics (`src/ablab/stats.py`)

Written from formulas rather than called from a library, so each is testable and explainable:

- **Welch / z difference in means** on sufficient statistics (n, mean, variance), so 14M rows
  reduce to six numbers in SQL. Binary metrics use the same code.
- **Relative lift CI by the delta method**: Var(m_t/m_c) ≈ v_t/m_c² + m_t²·v_c/m_c⁴.
- **SRM**: chi-square against the designed split, alarm at p < 0.001 (it runs on every test).
- **Power / sample size** with unequal variances and unequal splits (Criteo is 85/15).
- **CUPED**: y − θ(x − x̄), θ = cov(y, x)/var(x), pooled across arms. **CUPAC**: x is a
  cross-fitted model prediction from pre-assignment features.
- **Ratio metrics** (randomised by user, measured per session): delta-method variance,
  because sessions of one user are not independent.
- **mSPRT** always-valid p-values (normal mixture, Johari et al. 2017) for continuous monitoring.
- **Benjamini-Hochberg and Holm** for segment-level tests.
- **Complier (CACE) effect**: effect on users actually exposed, ITT / exposure rate.

## Criteo: why the readout is not just a t-test

The SRM check passes (85.00001%). But assignment can be predicted from features (AUC 0.509,
z = 42) and nine features differ by 10 to 63 standard errors. The dataset documentation says
it assembles several incrementality tests and was subsampled; tests with different treatment
shares and different baselines, pooled, make the naive difference in means confounded.

The give-away was CUPAC: under true randomisation, adjusting for a pre-assignment covariate
leaves the point estimate unchanged in expectation and only shrinks the variance. Here it
moved the visit effect from 1.03 pp to 0.73 pp. A large shift is a randomisation alarm, not a
variance-reduction win.

Estimators, all cross-fitted on two folds (a model never scores rows it trained on):

- **Propensity model**: gradient-boosted classifier, treatment ~ features, clipped to
  [0.01, 0.99].
- **Outcome models**: one per arm, outcome ~ features (for CUPAC: control arm only).
- Reported side by side: naive, CUPAC, propensity-stratified (20 strata), IPW (Horvitz-Thompson)
  and **AIPW**, which is consistent if either the propensity or the outcome model is right.
  AIPW is the headline; the others are checks.
- **Segments** use AIPW scores averaged within deciles of the control-trained baseline score:
  pre-assignment information only, so no post-treatment slicing.
- **Complier effect** = AIPW effect on the outcome / AIPW effect on exposure.

Validation on synthetic data with a known effect and an observed confounder
(`tests/test_criteo.py`): the naive CI excludes the truth; stratified, IPW and AIPW cover it.
When the confounder was only partly observed (the first version of that test), no estimator
recovered the truth, which is the honest limit of the method: it fixes observed imbalance only.

Compute: the readout holds 14M × 12 float32 features (670 MB) plus a few float64 vectors;
peak about 3.8 GB, 47 s with 4 threads. Models train on 0.4M to 2M sampled rows per fold
(conversion is rare, 0.2%, so it gets more rows) and predict in 1M-row chunks.

## GA4 simulations: testing the tests

Real users and outcomes, simulated assignment. Units are users with a session in Dec-Jan,
"assigned" at their first session in the window; November is the pre-period.

- **Injected lift**: non-buyers in treatment become buyers with the probability that raises the
  purchaser rate by the lift, and get a revenue drawn from real purchases. This keeps the
  revenue distribution realistic instead of multiplying every value.
- **Peeking**: a users × days matrix of cumulative revenue (196k × 62, 48 MB as float32). One
  experiment is six matrix-vector products, so 1,000 experiments with 62 looks take seconds.
- **Broken randomisation**: the bug removes treatment users who bounce (one session, no cart,
  no purchase), the realistic failure of a slow-loading variant. Removing random users would
  not bias anything and would make the exercise pointless.
- **Metric sensitivity**: days to 80% power from each metric's own variance, so the choice of
  primary metric is a measured decision.

## Dashboards

- **Evidence** (code): Markdown + SQL pages, built to a static site and deployed to GitHub
  Pages by CI. It reads a committed DuckDB file of aggregates only (3.6 MB), so CI needs no
  BigQuery credentials. The current Evidence template moved to a hosted CLI; this uses the
  open-source `@evidence-dev/evidence` 40.x build, with TypeScript pinned to 5 for its peers.
- **Power BI** (Windows; generated as a `.pbip` project by `tools/powerbi`, finished in Desktop):
  the same marts as CSV extracts in `powerbi/data`, read from GitHub so the report refreshes
  anywhere (the BigQuery sandbox tables expire); measures in `powerbi/measures.dax`. Rates are always ratios of sums, never averages of rates.

## Keeping the laptop usable

The previous project ran local models and heated the laptop. Here BigQuery does the heavy
SQL; locally every step is capped at 4 threads (`OMP_NUM_THREADS`, DuckDB `SET threads`),
heavy steps run under `nice`, and there is no Docker.
