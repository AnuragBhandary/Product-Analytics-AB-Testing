-- Window revenue in the experiment units equals the same window in fct_sessions and in the
-- daily table used for peeking.
with a as (select round(sum(revenue), 2) as v from {{ ref('exp_users') }}),

b as (
    select round(sum(revenue_usd), 2) as v from {{ ref('fct_sessions') }}
    where session_date between '{{ var("experiment_start") }}' and '{{ var("experiment_end") }}'
),

c as (select round(sum(revenue), 2) as v from {{ ref('exp_user_days') }})

select
    a.v as exp_users,
    b.v as sessions,
    c.v as user_days
from a, b, c
where a.v is null or b.v is null or c.v is null or a.v != b.v or b.v != c.v
