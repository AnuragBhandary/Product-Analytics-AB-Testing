select
    session_date as date,
    count(distinct user_pseudo_id) as users,
    count(*) as sessions,
    countif(is_engaged) / count(*) as engagement_rate,
    countif(converted) as converting_sessions,
    countif(converted) / count(*) as session_conversion_rate,
    sum(transactions) as purchases,
    sum(revenue_usd) as revenue_usd,
    safe_divide(sum(revenue_usd), sum(transactions)) as average_order_value_usd
from {{ ref('fct_sessions') }}
group by 1
