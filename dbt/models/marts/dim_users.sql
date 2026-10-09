-- One row per user: acquisition attributes and lifetime value inside the sample window.
with first_touch as (
    select
        user_pseudo_id,
        array_agg(
            struct(user_source, user_medium, device_category, country)
            order by event_ts limit 1
        )[offset(0)] as ft,
        min(event_date) as first_seen_date
    from {{ ref('stg_ga4__events') }}
    group by user_pseudo_id
),

activity as (
    select
        user_pseudo_id,
        count(*) as sessions,
        countif(is_engaged) as engaged_sessions,
        sum(transactions) as purchases,
        sum(revenue_usd) as revenue_usd,
        min(if(converted, session_date, null)) as first_purchase_date
    from {{ ref('fct_sessions') }}
    group by user_pseudo_id
)

select
    f.user_pseudo_id,
    f.first_seen_date,
    date_trunc(f.first_seen_date, isoweek) as cohort_week,
    f.ft.device_category as first_device_category,
    f.ft.country as first_country,
    f.ft.user_source as acquisition_source,
    f.ft.user_medium as acquisition_medium,
    {{ channel_group('f.ft.user_medium', 'f.ft.user_source') }} as acquisition_channel,
    coalesce(a.sessions, 0) as sessions,
    coalesce(a.engaged_sessions, 0) as engaged_sessions,
    coalesce(a.purchases, 0) as purchases,
    coalesce(a.revenue_usd, 0) as revenue_usd,
    a.first_purchase_date,
    date_diff(a.first_purchase_date, f.first_seen_date, day) as days_to_first_purchase
from first_touch as f
left join activity as a on f.user_pseudo_id = a.user_pseudo_id
