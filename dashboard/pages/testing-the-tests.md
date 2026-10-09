---
title: Testing the tests
---

A single experiment cannot tell you whether the analysis is calibrated. Here the 195,884 users
who visited in December-January are real (their sessions, purchases and very skewed revenue),
and only the assignment is simulated, thousands of times. So the truth is known.

## Calibration and power

With no effect (lift 0), every analysis should reject about 5% of the time. With an injected
lift, the rejection rate is the power.

```sql cal
select
    case when lift = 0 then 'A/A, no effect' else '+' || cast(round(lift * 100) as int) || '% lift' end as scenario,
    lift,
    analysis,
    rejection_rate
from ga4.sim_calibration
order by lift, analysis
```

<BarChart data={cal} x=analysis y=rejection_rate series=scenario type=grouped yFmt=pct0 swapXY=true title="Share of simulated experiments with p under 0.05" />

- A/A rejection rates are 4.1% to 5.7% over 2,000 experiments; revenue CIs cover the true lift
  94.6% to 95.1% of the time.
- Capping revenue at the 99th percentile of purchases raises power at a 10% lift from 34% to
  42%. CUPED and CUPAC barely move it: 97% of these users had no pre-period activity.

## Which metric should an experiment be powered on?

```sql sens
select
    'detect ' || cast(round(rel_mde * 100) as int) || '% lift' as target,
    metric,
    days_needed
from ga4.sim_metric_sensitivity
order by rel_mde desc, days_needed
```

<BarChart data={sens} x=metric y=days_needed series=target type=grouped swapXY=true yFmt=num0 title="Days of this store's traffic for 80% power, 50/50 split" />

At 3,159 users a day, a 10% lift in revenue per user needs about 190 days; the same lift in
add-to-cart rate needs 17. Powering on the sensitive metric and treating revenue as a
guardrail is the practical design here.

## Peeking

```sql peek
select
    lift,
    tau_rel,
    reject_single_final_look,
    reject_naive_daily_peeking,
    reject_msprt_daily_peeking,
    msprt_median_stop_day
from ga4.sim_peeking
order by lift, tau_rel
```

<DataTable data={peek}>
    <Column id=lift fmt=pct0 title="True lift" />
    <Column id=tau_rel fmt=pct0 title="mSPRT tuned for" />
    <Column id=reject_single_final_look fmt=pct1 title="One look at day 62" />
    <Column id=reject_naive_daily_peeking fmt=pct1 title="Naive, daily peeks" />
    <Column id=reject_msprt_daily_peeking fmt=pct1 title="mSPRT, daily peeks" />
    <Column id=msprt_median_stop_day fmt=num0 title="mSPRT median stop day" />
</DataTable>

Checking a naive p-value every day for 62 days and stopping at the first p under 0.05 declares a
winner in 29.7% of A/A tests. Always-valid p-values (mSPRT) keep that at 1.5%, and with a real
25% lift they stop at a median of day 18, at the cost of some power (73% vs 93% for one
planned look).

## Broken randomisation

A bug silently loses some treatment users who bounce (a slow script on the new page, say).

```sql srm
select * from ga4.sim_srm order by drop_share_of_treatment_bouncers
```

<DataTable data={srm}>
    <Column id=users_lost_share fmt=pct1 title="Treatment users lost" />
    <Column id=srm_alarm_rate fmt=pct0 title="SRM alarm (p under 0.001)" />
    <Column id=false_conversion_win_rate fmt=pct0 title="False conversion 'win' (p under 0.05)" />
    <Column id=mean_false_rel_lift_conversion fmt=pct1 title="Fake conversion lift" />
</DataTable>

Losing 2% of treatment users shows a fake +4.3% conversion lift, "significant" in 20% of runs;
the SRM check fires in 100% of them. Check the split before reading the result.
