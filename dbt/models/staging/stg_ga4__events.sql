-- Not date-partitioned: the BigQuery sandbox expires partitions 60 days after their
-- partition date, and this data is from 2020, so every partition would be deleted on write.
{{ config(cluster_by=['event_name', 'user_pseudo_id']) }}

-- One row per GA4 event, nested params flattened into the columns the marts use.
select
    parse_date('%Y%m%d', event_date) as event_date,
    timestamp_micros(event_timestamp) as event_ts,
    event_name,
    user_pseudo_id,
    {{ ga4_param('ga_session_id', 'int') }} as ga_session_id,
    concat(user_pseudo_id, '.', cast({{ ga4_param('ga_session_id', 'int') }} as string))
        as session_key,
    {{ ga4_param('ga_session_number', 'int') }} as ga_session_number,
    {{ ga4_param('page_location') }} as page_location,
    {{ ga4_param('engagement_time_msec', 'int') }} as engagement_time_msec,
    -- session_engaged arrives as a string on most events and as an int on some.
    coalesce(
        {{ ga4_param('session_engaged') }},
        cast({{ ga4_param('session_engaged', 'int') }} as string)
    ) = '1' as session_engaged,
    {{ ga4_param('entrances', 'int') }} = 1 as is_entrance,
    {{ ga4_param('source') }} as event_source,
    {{ ga4_param('medium') }} as event_medium,
    device.category as device_category,
    device.operating_system,
    device.web_info.browser,
    geo.country,
    traffic_source.source as user_source,
    traffic_source.medium as user_medium,
    timestamp_micros(user_first_touch_timestamp) as user_first_touch_ts,
    ecommerce.transaction_id,
    ecommerce.purchase_revenue_in_usd
from {{ source('ga4', 'events') }}
where _table_suffix between '{{ var("start_date") }}' and '{{ var("end_date") }}'
