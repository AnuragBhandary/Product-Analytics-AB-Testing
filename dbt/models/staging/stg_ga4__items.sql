{{ config(cluster_by=['event_name', 'item_id']) }}

-- One row per item on the ecommerce events that carry items.
select
    parse_date('%Y%m%d', e.event_date) as event_date,
    timestamp_micros(e.event_timestamp) as event_ts,
    e.event_name,
    e.user_pseudo_id,
    concat(e.user_pseudo_id, '.', cast({{ ga4_param('ga_session_id', 'int') }} as string))
        as session_key,
    e.ecommerce.transaction_id,
    i.item_id,
    i.item_name,
    i.item_category,
    i.price_in_usd,
    i.quantity,
    i.item_revenue_in_usd
from {{ source('ga4', 'events') }} as e, unnest(e.items) as i
where
    e._table_suffix between '{{ var("start_date") }}' and '{{ var("end_date") }}'
    and e.event_name in ('view_item', 'add_to_cart', 'begin_checkout', 'purchase')
