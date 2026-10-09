---
title: "A real experiment: Criteo incrementality test"
---

13,979,592 users from Criteo's public uplift dataset (v2.1). Treatment users could be shown
ads; control users were held out. Outcomes: a visit to the advertiser's site, and a conversion.

## 1. The split looks perfect...

The designed split is 85/15 and the observed split is 85.00001% (SRM p = 0.999).

## 2. ...but the groups are not alike

Under randomisation, features should match between arms to within about 0.0008 standard
deviations at this size. Several are 20 to 60 standard errors apart, and a model can predict
assignment from features (AUC 0.509, 42 standard errors above 0.5). The file pools several
incrementality tests that were subsampled, so the arms are not exchangeable. An SRM check
cannot see this, because the overall ratio is exactly right.

```sql balance
select feature, smd, z from ga4.criteo_balance order by abs(z) desc
```

<BarChart data={balance} x=feature y=z title="Feature imbalance, in standard errors (beyond ±2 is unusual)" />

## 3. So the naive lift is too high

Four estimators that adjust for the imbalance all sit below the naive difference in means. For
visits they agree closely (71% to 76% of the naive effect). For conversions they spread wider
(78% to 97%): CUPAC adjusts only along one predicted-baseline direction, while the
propensity-based estimators correct the assignment imbalance itself.

```sql est
select estimator, estimator_order, outcome, diff, ci_low, ci_high, rel_lift, share_of_naive
from ga4.criteo_estimates
order by outcome, estimator_order
```

```sql est_visit
select * from ${est} where outcome = 'visit'
```

<DataTable data={est_visit} title="Visit">
    <Column id=estimator />
    <Column id=diff fmt='0.00000' title="Effect (abs.)" />
    <Column id=ci_low fmt='0.00000' title="95% CI low" />
    <Column id=ci_high fmt='0.00000' title="95% CI high" />
    <Column id=rel_lift fmt=pct1 title="Relative lift" />
    <Column id=share_of_naive fmt=pct0 title="vs naive" />
</DataTable>

```sql est_conv
select * from ${est} where outcome = 'conversion'
```

<DataTable data={est_conv} title="Conversion">
    <Column id=estimator />
    <Column id=diff fmt='0.000000' title="Effect (abs.)" />
    <Column id=ci_low fmt='0.000000' title="95% CI low" />
    <Column id=ci_high fmt='0.000000' title="95% CI high" />
    <Column id=rel_lift fmt=pct1 title="Relative lift" />
    <Column id=share_of_naive fmt=pct0 title="vs naive" />
</DataTable>

The doubly robust (AIPW) estimate is the one to report: visits +19.5% (naive said +27.1%),
conversions +51.8% (naive said +59.4%). Among users who were actually exposed to an ad, the ad
caused a visit for about 21 in 100 (doubly robust complier effect, 95% CI 20.4 to 21.9).

## 4. Who responds

Users split into ten equal groups by their predicted baseline visit rate (from pre-assignment
features only). The top group produces most of the incremental outcomes.

```sql seg
select outcome, segment, diff, ci_low, ci_high, share_of_incremental, p_bh
from ga4.criteo_segments
order by outcome, segment
```

```sql seg_visit
select * from ${seg} where outcome = 'visit'
```

<BarChart data={seg_visit} x=segment y=share_of_incremental yFmt=pct0 title="Share of incremental visits by baseline-propensity decile" />

```sql seg_conv
select * from ${seg} where outcome = 'conversion'
```

<BarChart data={seg_conv} x=segment y=share_of_incremental yFmt=pct0 title="Share of incremental conversions by baseline-propensity decile" />

Decile 10 accounts for 63% of incremental visits and 82% of incremental conversions
(Benjamini-Hochberg adjusted across deciles).
