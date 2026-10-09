-- Item funnel: views -> carts -> purchases. Purchase items come only from the purchase events
-- kept in int_purchases, so duplicated purchase events do not double-count units.
with items as (
    select * from {{ ref('stg_ga4__items') }}
),

kept_purchases as (
    select
        user_pseudo_id,
        purchase_ts as event_ts
    from {{ ref('int_purchases') }}
),

browsing as (
    select
        item_name,
        any_value(item_category) as item_category,
        countif(event_name = 'view_item') as item_views,
        count(distinct if(event_name = 'view_item', session_key, null)) as sessions_viewed,
        sum(if(event_name = 'add_to_cart', quantity, 0)) as units_added_to_cart
    from items
    where event_name in ('view_item', 'add_to_cart')
    group by item_name
),

purchased as (
    select
        i.item_name,
        any_value(i.item_category) as item_category,
        sum(i.quantity) as units_purchased,
        sum(i.item_revenue_in_usd) as item_revenue_usd
    from items as i
    inner join kept_purchases as k
        on i.user_pseudo_id = k.user_pseudo_id and i.event_ts = k.event_ts
    where i.event_name = 'purchase'
    group by i.item_name
)

select
    item_name,
    coalesce(b.item_category, p.item_category) as item_category,
    coalesce(b.item_views, 0) as item_views,
    coalesce(b.sessions_viewed, 0) as sessions_viewed,
    coalesce(b.units_added_to_cart, 0) as units_added_to_cart,
    coalesce(p.units_purchased, 0) as units_purchased,
    coalesce(p.item_revenue_usd, 0) as item_revenue_usd
from browsing as b
full outer join purchased as p using (item_name)
