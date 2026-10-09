-- Every (user, ga_session_id) in the raw export is exactly one row in fct_sessions.
with raw as (
    select count(distinct concat(user_pseudo_id, '.', cast(ga_session_id as string))) as n
    from {{ ref('stg_ga4__events') }}
    where ga_session_id is not null
),

modelled as (select count(*) as n from {{ ref('fct_sessions') }})

select
    raw.n as raw_sessions,
    modelled.n as fct_sessions
from raw, modelled
where raw.n = 0 or raw.n != modelled.n
