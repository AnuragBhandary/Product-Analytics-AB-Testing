-- Not date-partitioned: the BigQuery sandbox expires partitions 60 days after their
-- partition date, and this data is from 2020, so every partition would be deleted on write.
{{ config(cluster_by=['channel', 'device_category']) }}

-- One row per session (user_pseudo_id + ga_session_id), with funnel flags and revenue.
with events as (
    select * from {{ ref('stg_ga4__events') }}
    where ga_session_id is not null
),

purchases as (
    select
        session_key,
        count(*) as transactions,
        sum(revenue_usd) as revenue_usd
    from {{ ref('int_purchases') }}
    group by session_key
),

sessions as (
    select
        session_key,
        any_value(user_pseudo_id) as user_pseudo_id,
        min(event_date) as session_date,
        min(event_ts) as session_start_ts,
        max(event_ts) as session_end_ts,
        max(ga_session_number) as session_number,
        -- Attributes of the first event in the session.
        array_agg(device_category order by event_ts limit 1)[offset(0)] as device_category,
        array_agg(country order by event_ts limit 1)[offset(0)] as country,
        array_agg(
            regexp_extract(page_location, r'^https?://[^/]+(/[^?#]*)') ignore nulls
            order by event_ts limit 1
        )[safe_offset(0)] as landing_path,
        array_agg(event_medium ignore nulls order by event_ts limit 1)[safe_offset(0)]
            as session_medium,
        array_agg(event_source ignore nulls order by event_ts limit 1)[safe_offset(0)]
            as session_source,
        -- User-scoped first-touch source: present on every event, unlike the session source.
        any_value(user_medium) as user_medium,
        any_value(user_source) as user_source,
        logical_or(session_engaged) as is_engaged,
        countif(event_name = 'page_view') as page_views,
        coalesce(sum(engagement_time_msec), 0) / 1000 as engagement_seconds,
        logical_or(event_name = 'view_item') as did_view_item,
        logical_or(event_name = 'add_to_cart') as did_add_to_cart,
        logical_or(event_name = 'begin_checkout') as did_begin_checkout,
        logical_or(event_name = 'add_shipping_info') as did_add_shipping_info,
        logical_or(event_name = 'add_payment_info') as did_add_payment_info,
        logical_or(event_name = 'purchase') as did_purchase_event
    from events
    group by session_key
)

select
    s.*,
    -- 26% of sessions carry no session source on any event (mostly 1-page bounces), so the
    -- session channel keeps an explicit 'Unknown'; acquisition_channel is complete.
    {{ channel_group('s.session_medium', 's.session_source') }} as channel,
    {{ channel_group('s.user_medium', 's.user_source') }} as acquisition_channel,
    coalesce(p.transactions, 0) as transactions,
    coalesce(p.revenue_usd, 0) as revenue_usd,
    coalesce(p.transactions, 0) > 0 as converted
from sessions as s
left join purchases as p on s.session_key = p.session_key
