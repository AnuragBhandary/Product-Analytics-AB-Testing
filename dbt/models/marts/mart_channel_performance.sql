-- Performance by the user's acquisition channel (first-touch, known for every session).
-- Session-level channel is in fct_sessions; a quarter of it is 'Unknown', see DESIGN.md.
select
    acquisition_channel,
    device_category,
    count(distinct user_pseudo_id) as users,
    count(*) as sessions,
    countif(is_engaged) / count(*) as engagement_rate,
    countif(converted) as converting_sessions,
    countif(converted) / count(*) as session_conversion_rate,
    sum(revenue_usd) as revenue_usd,
    sum(revenue_usd) / count(*) as revenue_per_session_usd,
    countif(channel = 'Unknown') / count(*) as share_sessions_without_session_source
from {{ ref('fct_sessions') }}
group by 1, 2
