-- A closed funnel can only lose sessions from one step to the next.
select *
from {{ ref('mart_funnel_weekly') }}
where
    closed_add_to_cart > closed_view_item
    or closed_begin_checkout > closed_add_to_cart
    or closed_add_shipping_info > closed_begin_checkout
    or closed_add_payment_info > closed_add_shipping_info
    or closed_purchase > closed_add_payment_info
    or open_view_item > sessions
