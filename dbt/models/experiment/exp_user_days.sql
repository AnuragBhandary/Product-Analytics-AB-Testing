-- Daily outcomes per experiment user, for the peeking simulation.
select
    user_pseudo_id,
    date_diff(session_date, '{{ var("experiment_start") }}', day) as day_index,
    count(*) as sessions,
    sum(transactions) as purchases,
    sum(revenue_usd) as revenue
from {{ ref('fct_sessions') }}
where session_date between '{{ var("experiment_start") }}' and '{{ var("experiment_end") }}'
group by 1, 2
