select
    p.purchase_key,
    p.transaction_id,
    p.has_transaction_id,
    p.user_pseudo_id,
    p.session_key,
    p.purchase_date,
    p.purchase_ts,
    p.revenue_usd,
    p.events_logged,
    s.device_category,
    s.country,
    s.channel
from {{ ref('int_purchases') }} as p
left join {{ ref('fct_sessions') }} as s on p.session_key = s.session_key
