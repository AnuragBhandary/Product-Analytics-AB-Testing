---
title: Checkout funnel
---

A closed funnel counts a session at a step only if it also did every earlier step, so it can
never rise. The open funnel counts each step on its own. Purchases in the open funnel (4,446)
exceed the closed funnel (2,573) because 42% of converting sessions had no add-to-cart in that
session: the cart was filled in an earlier visit and persisted.

```sql closed
select 'View item' as step, 1 as ord, sum(closed_view_item) as sessions from ga4.funnel_weekly
union all select 'Add to cart', 2, sum(closed_add_to_cart) from ga4.funnel_weekly
union all select 'Begin checkout', 3, sum(closed_begin_checkout) from ga4.funnel_weekly
union all select 'Shipping info', 4, sum(closed_add_shipping_info) from ga4.funnel_weekly
union all select 'Payment info', 5, sum(closed_add_payment_info) from ga4.funnel_weekly
union all select 'Purchase', 6, sum(closed_purchase) from ga4.funnel_weekly
order by ord
```

<FunnelChart data={closed} nameCol=step valueCol=sessions title="Closed funnel, all sessions" />

```sql by_device
select
    device_category,
    sum(sessions) as sessions,
    sum(open_view_item) / sum(sessions) as view_item_rate,
    sum(open_add_to_cart) / sum(open_view_item) as view_to_cart,
    sum(open_begin_checkout) / sum(open_add_to_cart) as cart_to_checkout,
    sum(open_purchase) / sum(open_begin_checkout) as checkout_to_purchase,
    sum(open_purchase) / sum(sessions) as session_conversion
from ga4.funnel_weekly
group by 1
order by sessions desc
```

<DataTable data={by_device}>
    <Column id=device_category title="Device" />
    <Column id=sessions fmt=num0 />
    <Column id=view_item_rate fmt=pct1 title="Viewed an item" />
    <Column id=view_to_cart fmt=pct1 title="View → cart" />
    <Column id=cart_to_checkout fmt=pct1 title="Cart → checkout" />
    <Column id=checkout_to_purchase fmt=pct1 title="Checkout → purchase" />
    <Column id=session_conversion fmt=pct2 title="Session conversion" />
</DataTable>

```sql weekly
select
    week,
    sum(open_add_to_cart) / sum(open_view_item) as view_to_cart,
    sum(open_purchase) / sum(open_begin_checkout) as checkout_to_purchase
from ga4.funnel_weekly
group by 1
order by 1
```

<LineChart data={weekly} x=week y={['view_to_cart', 'checkout_to_purchase']} yFmt=pct0 title="Weekly step conversion" />
