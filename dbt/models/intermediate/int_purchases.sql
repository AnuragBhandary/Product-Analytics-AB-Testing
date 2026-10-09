-- One row per real purchase.
-- * 306 transactions were logged twice (same id, user and revenue): keep the first event.
-- * 15 ids are shared by two different users with different revenue (obfuscation collisions):
--   the key is id + user, so both purchases count.
-- * 883 events carry transaction_id '(not set)' and 23 carry null: they cannot be deduplicated
--   by id, so each event is its own purchase; the 450 of them with zero revenue are dropped.
with purchases as (
    select
        *,
        transaction_id is not null and transaction_id != '(not set)' as has_transaction_id
    from {{ ref('stg_ga4__events') }}
    where event_name = 'purchase'
),

keyed as (
    select
        *,
        if(
            has_transaction_id,
            concat(transaction_id, '|', user_pseudo_id),
            concat('event|', user_pseudo_id, '|', cast(unix_micros(event_ts) as string))
        ) as purchase_key
    from purchases
    where has_transaction_id or purchase_revenue_in_usd > 0
)

select
    purchase_key,
    transaction_id,
    has_transaction_id,
    user_pseudo_id,
    session_key,
    event_date as purchase_date,
    event_ts as purchase_ts,
    purchase_revenue_in_usd as revenue_usd,
    count(*) over (partition by purchase_key) as events_logged
from keyed
qualify row_number() over (partition by purchase_key order by event_ts) = 1
