-- Weekly acquisition cohorts: share of each cohort with a session N weeks after first visit.
-- 2020-10-26's ISO week holds only 2020-11-01 (the sample starts on a Sunday), so cohorts
-- start at 2020-11-02. Later cohorts have fewer observable weeks; that is right-censoring,
-- not churn, and weeks past the sample end are simply absent.
with users as (
    select
        user_pseudo_id,
        cohort_week
    from {{ ref('dim_users') }}
    where cohort_week >= '2020-11-02'
),

activity as (
    select distinct
        user_pseudo_id,
        date_trunc(session_date, isoweek) as active_week
    from {{ ref('fct_sessions') }}
),

cohort_sizes as (
    select
        cohort_week,
        count(*) as cohort_users
    from users
    group by 1
)

select
    u.cohort_week,
    date_diff(a.active_week, u.cohort_week, week) as week_number,
    c.cohort_users,
    count(distinct u.user_pseudo_id) as active_users,
    count(distinct u.user_pseudo_id) / c.cohort_users as retention
from users as u
inner join activity as a on u.user_pseudo_id = a.user_pseudo_id
inner join cohort_sizes as c on u.cohort_week = c.cohort_week
where a.active_week >= u.cohort_week
group by 1, 2, 3
