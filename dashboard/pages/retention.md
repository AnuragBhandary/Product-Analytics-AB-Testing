---
title: Retention cohorts
---

Weekly acquisition cohorts: the share of each cohort with a session N weeks after its first
visit. Later cohorts have fewer observable weeks (the sample ends on 31 Jan 2021); missing
cells are right-censoring, not churn.

```sql cohorts
select
    strftime(cohort_week, '%Y-%m-%d') as cohort,
    week_number,
    retention,
    cohort_users
from ga4.cohort_retention
where week_number between 1 and 12
order by cohort_week, week_number
```

<Heatmap data={cohorts} x=week_number y=cohort value=retention valueFmt=pct1 title="Retention by cohort, weeks 1-12" />

```sql curve
select
    week_number,
    sum(active_users) / sum(cohort_users) as retention
from ga4.cohort_retention
where week_number >= 1
group by 1
order by 1
```

<LineChart data={curve} x=week_number y=retention yFmt=pct1 title="Pooled retention curve (users with that week observable)" />

Only about 4% of users come back the week after their first visit, and about 1% are
active a month later. That matters for experiments: 97% of users in a December-January test
have no November history, so CUPED (which leans on pre-period behaviour) has almost nothing
to work with. See [Testing the tests](/testing-the-tests).
