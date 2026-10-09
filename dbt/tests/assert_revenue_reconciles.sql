-- Revenue three ways must agree to the cent:
--   1. an independent dedup of raw purchase events (distinct id + user + revenue, plus every
--      non-zero event without a usable id), straight from the public source;
--   2. fct_purchases; 3. fct_sessions (purchases attached to sessions).
with raw_events as (
    select
        user_pseudo_id,
        ecommerce.transaction_id as tid,
        ecommerce.purchase_revenue_in_usd as rev,
        event_timestamp
    from {{ source('ga4', 'events') }}
    where
        event_name = 'purchase'
        and _table_suffix between '{{ var("start_date") }}' and '{{ var("end_date") }}'
),

with_id as (
    select distinct
        tid,
        user_pseudo_id,
        rev
    from raw_events
    where tid is not null and tid != '(not set)'
),

without_id as (
    select rev from raw_events
    where (tid is null or tid = '(not set)') and rev > 0
),

totals as (
    select
        round((select sum(rev) from with_id) + (select sum(rev) from without_id), 2) as raw_rev,
        round((select sum(revenue_usd) from {{ ref('fct_purchases') }}), 2) as fct_rev,
        round((select sum(revenue_usd) from {{ ref('fct_sessions') }}), 2) as session_rev
)

-- Nulls fail too: an empty model must not pass by comparing NULL with NULL.
select * from totals
where
    raw_rev is null or fct_rev is null or session_rev is null
    or raw_rev != fct_rev or fct_rev != session_rev
