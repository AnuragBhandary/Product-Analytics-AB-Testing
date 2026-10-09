-- Units for the simulated experiments: every user with a session in the window
-- (experiment_start .. experiment_end), "assigned" at their first session in it.
-- Pre-period activity (before experiment_start) is the CUPED covariate; device, country and
-- channel of the assignment session feed the CUPAC model. Nothing here is measured after
-- assignment except the outcomes.
with s as (
    select * from {{ ref('fct_sessions') }}
),

in_window as (
    select *
    from s
    where session_date between '{{ var("experiment_start") }}' and '{{ var("experiment_end") }}'
),

arrival as (
    select
        user_pseudo_id,
        array_agg(
            struct(session_date, device_category, country, acquisition_channel as channel)
            order by session_start_ts limit 1
        )[offset(0)] as first_session
    from in_window
    group by 1
),

outcomes as (
    select
        user_pseudo_id,
        count(*) as sessions,
        countif(converted) as converted_sessions,
        countif(did_add_to_cart) as cart_sessions,
        sum(transactions) as purchases,
        sum(revenue_usd) as revenue
    from in_window
    group by 1
),

pre as (
    select
        user_pseudo_id,
        count(*) as pre_sessions,
        sum(transactions) as pre_purchases,
        sum(revenue_usd) as pre_revenue,
        countif(did_add_to_cart) as pre_cart_sessions
    from s
    where session_date < '{{ var("experiment_start") }}'
    group by 1
)

select
    a.user_pseudo_id,
    date_diff(a.first_session.session_date, '{{ var("experiment_start") }}', day) as arrival_day,
    a.first_session.device_category,
    a.first_session.device_category = 'mobile' as is_mobile,
    a.first_session.country,
    a.first_session.channel,
    o.sessions,
    o.converted_sessions,
    if(o.purchases > 0, 1, 0) as purchaser,
    if(o.cart_sessions > 0, 1, 0) as carted,
    o.revenue,
    coalesce(p.pre_sessions, 0) as pre_sessions,
    coalesce(p.pre_purchases, 0) as pre_purchases,
    coalesce(p.pre_revenue, 0) as pre_revenue,
    coalesce(p.pre_cart_sessions, 0) as pre_cart_sessions
from arrival as a
inner join outcomes as o on a.user_pseudo_id = o.user_pseudo_id
left join pre as p on a.user_pseudo_id = p.user_pseudo_id
