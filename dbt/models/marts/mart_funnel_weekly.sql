-- Checkout funnel per week x device x channel.
-- open_*: sessions that did the step at all. closed_*: sessions that did it AND every earlier
-- step (GA's "closed funnel"); closed counts can only fall from step to step.
select
    date_trunc(session_date, isoweek) as week,
    device_category,
    channel,
    count(*) as sessions,
    countif(did_view_item) as open_view_item,
    countif(did_add_to_cart) as open_add_to_cart,
    countif(did_begin_checkout) as open_begin_checkout,
    countif(did_add_shipping_info) as open_add_shipping_info,
    countif(did_add_payment_info) as open_add_payment_info,
    countif(converted) as open_purchase,
    countif(did_view_item) as closed_view_item,
    countif(did_view_item and did_add_to_cart) as closed_add_to_cart,
    countif(did_view_item and did_add_to_cart and did_begin_checkout) as closed_begin_checkout,
    countif(
        did_view_item and did_add_to_cart and did_begin_checkout and did_add_shipping_info
    ) as closed_add_shipping_info,
    countif(
        did_view_item and did_add_to_cart and did_begin_checkout and did_add_shipping_info
        and did_add_payment_info
    ) as closed_add_payment_info,
    countif(
        did_view_item and did_add_to_cart and did_begin_checkout and did_add_shipping_info
        and did_add_payment_info and converted
    ) as closed_purchase
from {{ ref('fct_sessions') }}
group by 1, 2, 3
