# Interview guide

How to learn this project, pitch it, and defend it in a data analyst, product analyst or data
scientist (experimentation) interview. Numbers: [RESULTS.md](RESULTS.md). Reasoning:
[DESIGN.md](DESIGN.md).

## 1. Learning path (read in this order)

| # | File | What to be able to explain afterwards |
|---|---|---|
| 1 | `dbt/models/staging/stg_ga4__events.sql`, `macros/ga4_param.sql` | GA4 export schema: one table per day, `event_params` as an array of key/value structs, why `UNNEST` in a scalar subquery, `_TABLE_SUFFIX` |
| 2 | `dbt/models/intermediate/int_purchases.sql` | The four purchase-data problems and the key that handles each; `QUALIFY ROW_NUMBER()` |
| 3 | `dbt/models/marts/fct_sessions.sql` | Session key; first-event attributes with `ARRAY_AGG(... ORDER BY ... LIMIT 1)`; session vs acquisition channel and why 26% is Unknown |
| 4 | `marts/mart_funnel_weekly.sql` | Open vs closed funnel; why closed is monotone; why it undercounts (cart filled in an earlier session) |
| 5 | `marts/mart_cohort_retention.sql` | Cohort definition, week number, right-censoring, pooled vs averaged retention |
| 6 | `dbt/tests/*.sql`, `_marts.yml` | What each test guards; why the original tests passed on empty tables and how they now fail |
| 7 | `src/ablab/stats.py` | Every formula by hand: Welch SE, delta-method lift CI, chi-square SRM, sample size, CUPED θ, ratio-metric variance, mSPRT, BH vs Holm |
| 8 | `src/ablab/criteo.py` | Balance check, cross-fitting, propensity, IPW, AIPW, stratification, CACE, segment effects |
| 9 | `src/ablab/simulate.py` | How lift is injected, the peeking matrix, the SRM bug model, metric sensitivity |
| 10 | `tests/` | What each test proves (scipy cross-checks, coverage of CIs, synthetic confounding) |
| 11 | `dashboard/pages/*.md`, `powerbi/measures.dax` | Each chart's query; DAX for ratios of sums, time intelligence, the what-if sample-size calculator |

Exercise after each file: close it and write the key query or formula on paper. Two to drill:
the sample size for a 10% relative lift on a 5% conversion rate (about 31,000 per arm), and
CUPED's variance reduction when corr(x, y) = 0.5 (25%).

## 2. The 60-second pitch

> "I built a product analytics and experimentation project in two parts. First, I modelled
> Google's GA4 ecommerce sample, 4.3 million events, in BigQuery with dbt: sessions, funnels,
> cohorts, channels and products, with tests that reconcile revenue to the cent against an
> independent deduplication of the raw events. That surfaced real data problems: duplicate
> purchase events worth 6% of revenue, and a quarter of sessions with no traffic source,
> mostly bounces, which would have inflated conversion by a third if dropped.
> Second, I built the A/B testing statistics myself and tested them before trusting them:
> thousands of simulated experiments on real GA4 users show the tests hold a 5% false-positive
> rate, that checking results daily pushes it to 30%, and that sequential tests fix that. It
> also showed that revenue per user is so noisy this store would need 190 days to detect a 10%
> lift, against 17 days for add-to-cart rate, which is how you choose a primary metric.
> Then I read out a real 14-million-user ad experiment from Criteo. The sample ratio check
> passed, but covariate balance failed: the data pools several tests, so the naive lift of 27%
> was confounded. Four adjusted estimators agreed on about 19.5%. The dashboards are Evidence,
> built and deployed by CI, and Power BI."

## 3. Numbers to know cold

| | |
|---|---|
| GA4 | 4,295,584 events; 360,129 sessions; 270,154 users; 4,922 purchases; $340,647 |
| Conversion / AOV | 1.23% of sessions; $69.21 |
| Retention | 4.2% week 1, about 1% week 4 |
| Data issues | 314 duplicated purchases ($21,518, 6.3%); 26% of sessions without a source |
| dbt | 13 models, 27 data tests, about 60 s, 4.7 GB scanned |
| Criteo | 13,979,592 users, 85/15; SRM p = 0.999; AUC 0.509 (z = 42) |
| Criteo visit lift | naive +27.1% → AIPW +19.5% (CI +18.9% to +20.2% relative) |
| Criteo conversion lift | naive +59.4% → AIPW +51.8% |
| Complier effect | an exposure causes a visit for 21% of exposed users |
| Top decile | 63% of incremental visits, 82% of incremental conversions |
| Power check | predicted 80.9% vs observed 81.0%; A/A 4.5% and 5.0% |
| GA4 A/A | 4.1% to 5.7% across seven analyses; CI coverage 94.6% to 95.1% |
| Days for +10% | revenue 190, capped revenue 147, purchaser rate 72, add-to-cart 17 |
| Peeking | naive 29.7% false positives; mSPRT 1.5%; stops at day 18 with 73% power at +25% |
| SRM bug | lose 2% of treatment bouncers → alarm 100%, fake +4.3% conversion lift |
| CUPED on GA4 | 0.24% variance removed (97% of users are new) |

## 4. Likely questions

**Product analytics / SQL**

- *How do you get a parameter out of `event_params`?* A scalar subquery over `UNNEST`: select
  `value.int_value` where `key = 'ga_session_id'`. The value struct has one typed field per
  type; `session_engaged` arrives as both string and int, hence the `COALESCE`.
- *What is a session in GA4?* `user_pseudo_id` + `ga_session_id`. GA4 has no session table;
  you build it. The test checks the count equals the distinct pairs in the raw data.
- *Why is your closed funnel lower than purchases?* It is session-scoped and 42% of buyers
  carted in an earlier session. A user-scoped funnel (did each step within N days) would fix
  it; I show both open and closed and say which question each answers.
- *Why not drop sessions without a source?* They are not random: mostly bounces. Dropping
  them overstates conversion by 36%. Unknown is a real category; first-touch channel is
  complete, so channel comparisons use that.
- *Why is retention pooled as sum of actives over sum of cohort sizes?* Averaging percentages
  gives a 200-user cohort the same weight as a 30,000-user one.
- *Duplicates?* Same id, user and revenue logged twice: keep one. Same id on two users with
  different revenue: obfuscation collision, keep both. No id: cannot dedupe, keep non-zero.
- *A test passed on an empty table: how?* `WHERE a != b` with both NULL returns no rows, and
  dbt treats no rows as a pass. Fixed with explicit NULL checks and row-count bounds.

**Experiment design**

- *Walk me through designing a test.* Hypothesis and decision rule first; one primary metric
  chosen for sensitivity and relevance (here add-to-cart, with revenue and conversion as
  guardrails); MDE from what is worth shipping; sample size and duration from the power
  formula and real traffic (cover full weeks); randomisation unit = user; SRM and A/A checks;
  no peeking unless the test is sequential; analysis plan written before launch.
- *Why does revenue per user need so long?* Its standard deviation is 14× its mean (most
  users spend 0, a few spend hundreds). Required n scales with (σ/μ)²/MDE².
- *CUPED: when does it help?* When the covariate correlates with the outcome; variance falls by
  ρ². Here 97% of users have no pre-period, so ρ is about 0.05. On Criteo's features (CUPAC) it
  removed 32% of the visit variance.
- *What is SRM and why p < 0.001?* Observed split vs designed split, chi-square. It runs on
  every test, so a strict threshold limits false alarms; a real bug produces tiny p-values
  (losing 2% of one arm gave 100% alarms).
- *Why is peeking a problem?* Each look is another chance for noise to cross 1.96. Over 62
  daily looks, 29.7% of no-effect tests "win". Fixes: fixed horizon, alpha spending, or
  always-valid p-values (mSPRT), which cost some power in exchange for stopping early.
- *Ratio metrics?* If you randomise users but compute per-session rates, sessions of the same
  user are correlated; the delta method gives the right variance. On this data the difference
  was small because 84% of users have one session, and I say that.
- *Multiple segments?* Benjamini-Hochberg for discovery across ten deciles (controls the share
  of false discoveries); Holm if any single false positive is costly.
- *Novelty effects, interference?* Not testable here (no real treatment on GA4), but: plot the
  effect by days since exposure; for marketplaces randomise by cluster or use switchbacks.

**Causal inference (Criteo)**

- *The SRM check passed. Why not trust the t-test?* Balance failed: features differ by up to
  63 standard errors and predict assignment (AUC 0.509, z = 42). A ratio check only sees the
  total; the pooled tests differ in treatment share and baseline, so arm membership is
  correlated with baseline propensity.
- *What tipped you off?* CUPAC moved the point estimate by 29%. With true randomisation a
  pre-period covariate changes variance, not the estimate (in expectation).
- *Explain AIPW.* Outcome-model difference plus inverse-propensity-weighted residuals. It is
  consistent if either model is right, and its variance is near the efficient bound.
  Cross-fitting stops a model from scoring rows it trained on, which would bias it.
- *Why report four estimators?* They make different assumptions (stratification is coarse,
  IPW is noisy, CUPAC adjusts along one direction). Agreement is the robustness check; AIPW is
  the headline.
- *What can't adjustment fix?* Unobserved confounders. My synthetic test shows it: with the
  confounder only partly observed, no estimator recovered the truth.
- *What is the complier effect?* ITT divided by the exposure rate: the effect on people who
  actually saw an ad (21% of them visited because of it), valid because control users could not
  be exposed.
- *How would you use the segments?* Target the top decile: it produces 63% of incremental
  visits. Segments come from pre-assignment features only, otherwise you would be slicing on
  a post-treatment variable.

**BI**

- *DAX for a conversion rate?* `DIVIDE(SUM(converting), SUM(sessions))`, never an average of
  daily rates. Time intelligence needs a marked date table.
- *Why Import mode?* Tiny tables, and the sandbox deletes tables after 60 days; Import keeps
  the report working.
- *Why two dashboards?* Evidence is code: reviewed in PRs, built in CI, versioned with the
  models. Power BI is what most teams use day to day.

## 5. Stories (STAR)

**The tests that passed on nothing.** *S:* the first dbt build reported 38 of 38 passing. *T:*
publish the marts. *A:* I checked results before trusting the green run; every table was
empty. The sandbox expires partitions 60 days after their date, and the 2020 data was deleted
on write; the reconciliation tests compared NULL with NULL and returned no rows, which counts
as a pass. I removed date partitioning, made every reconciliation fail on NULL, and added a
row-count test from profiled bounds. *R:* 27 data tests that now fail on empty input; a habit of
checking that a "pass" could have failed.

**The experiment whose split was perfect.** *S:* Criteo's 14M-user test, SRM p = 0.999. *T:*
read out the lift. *A:* CUPAC moved the estimate by 29%, which randomisation should not allow.
I checked balance (up to 63 standard errors), trained a model to predict assignment (AUC
0.509, z = 42), found the documentation says the file pools several tests, and switched to
propensity-based estimators with cross-fitting. *R:* naive +27.1% → +19.5%, four estimators
agreeing; a synthetic test showing both when it works and when it cannot.

**Choosing the metric.** *S:* the natural primary metric for a store is revenue per user. *T:*
size a test. *A:* I measured each candidate metric's variance on real users. *R:* revenue needs
190 days for a 10% lift and CUPED cannot help (97% new users); add-to-cart needs 17. Recommend
add-to-cart as primary with revenue and conversion as guardrails.

**The bounce sessions.** *S:* a quarter of sessions had no channel. *T:* channel report. *A:*
profiled them instead of filtering: 1.5 page views and 11 s on average, almost no purchases.
*R:* dropping them would have overstated conversion by 36%; reported by first-touch channel.

## 6. What I would do next

- A user-scoped funnel (steps within 7 days) to fix the session-scope undercount.
- Alpha spending (O'Brien-Fleming) next to mSPRT, compared on the same peeking simulations.
- A heterogeneous-effect model (causal forest or X-learner) on Criteo, compared to the decile
  view on a held-out uplift (Qini) curve.
- Run the dbt build on a schedule with freshness checks if the source were live.
