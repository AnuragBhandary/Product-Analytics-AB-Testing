---
title: Google Merchandise Store, Nov 2020 to Jan 2021
---

GA4's public ecommerce sample (obfuscated), modelled with dbt in BigQuery. Every number on these
pages comes from tested models: sessions reconcile to the raw export, and revenue reconciles to
an independent deduplication of purchase events, to the cent.

```sql totals
select
    sum(sessions) as sessions,
    sum(purchases) as purchases,
    sum(revenue_usd) as revenue_usd,
    sum(converting_sessions) / sum(sessions) as session_conversion_rate,
    sum(revenue_usd) / sum(purchases) as aov
from ga4.daily_kpis
```

<BigValue data={totals} value=sessions fmt=num0 />
<BigValue data={totals} value=purchases fmt=num0 />
<BigValue data={totals} value=revenue_usd title="Revenue" fmt=usd0k />
<BigValue data={totals} value=session_conversion_rate title="Session conversion" fmt=pct2 />
<BigValue data={totals} value=aov title="Average order" fmt=usd2 />

```sql daily
select date, sessions, revenue_usd, session_conversion_rate
from ga4.daily_kpis
order by date
```

<LineChart data={daily} x=date y=revenue_usd yFmt=usd0 title="Daily revenue" />
<LineChart data={daily} x=date y=sessions yFmt=num0 title="Daily sessions" />

## Channels

Grouped by the user's acquisition channel (first touch), which every session has. The
session-level source is missing on 26% of sessions, almost all one-page bounces; dropping them
would overstate every channel's conversion rate by about a third.

```sql channels
select
    acquisition_channel,
    sum(users) as users,
    sum(sessions) as sessions,
    sum(converting_sessions) / sum(sessions) as conversion_rate,
    sum(revenue_usd) as revenue_usd,
    sum(revenue_usd) / sum(sessions) as revenue_per_session
from ga4.channel_performance
group by 1
order by sessions desc
```

<DataTable data={channels}>
    <Column id=acquisition_channel title="Channel" />
    <Column id=users fmt=num0 />
    <Column id=sessions fmt=num0 />
    <Column id=conversion_rate fmt=pct2 contentType=colorscale />
    <Column id=revenue_usd fmt=usd0 title="Revenue" />
    <Column id=revenue_per_session fmt=usd2 title="Revenue / session" />
</DataTable>

## Pages

- [Checkout funnel](/funnel)
- [Retention cohorts](/retention)
- [Products](/products)
- [A real experiment: Criteo, 14M users](/criteo-experiment)
- [Testing the tests: simulations on GA4 users](/testing-the-tests)
