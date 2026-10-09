---
title: Products
---

Item-level funnel. Purchased units come only from deduplicated purchase events, so the 314
transactions GA4 logged twice are not double-counted.

```sql products
select
    item_name,
    item_category,
    item_views,
    units_added_to_cart,
    units_purchased,
    item_revenue_usd,
    units_purchased / nullif(sessions_viewed, 0) as units_per_viewing_session
from ga4.product_performance
where item_views >= 500
order by item_revenue_usd desc
```

<BarChart data={products.slice(0, 15)} x=item_name y=item_revenue_usd swapXY=true yFmt=usd0 title="Top 15 items by revenue" />

<DataTable data={products} search=true rows=20>
    <Column id=item_name title="Item" />
    <Column id=item_category title="Category" />
    <Column id=item_views fmt=num0 title="Views" />
    <Column id=units_added_to_cart fmt=num0 title="Added to cart" />
    <Column id=units_purchased fmt=num0 title="Units bought" />
    <Column id=item_revenue_usd fmt=usd0 title="Revenue" />
    <Column id=units_per_viewing_session fmt=pct1 title="Units / viewing session" contentType=colorscale />
</DataTable>
