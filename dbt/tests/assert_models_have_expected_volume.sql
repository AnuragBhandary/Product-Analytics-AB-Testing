-- Guards against silently empty or truncated builds (the sandbox once deleted every
-- partition on write and all other tests still passed). Bounds come from profiling the raw
-- export: 4,295,584 events, 360k sessions, 270k users.
with counts as (
    select *
    from unnest([
        struct(
            'stg_ga4__events' as model,
            (select count(*) from {{ ref('stg_ga4__events') }}) as n,
            4295584 as lo,
            4295584 as hi
        ),
        ('fct_sessions', (select count(*) from {{ ref('fct_sessions') }}), 300000, 400000),
        ('dim_users', (select count(*) from {{ ref('dim_users') }}), 260000, 280000),
        ('fct_purchases', (select count(*) from {{ ref('fct_purchases') }}), 4000, 6000),
        ('exp_users', (select count(*) from {{ ref('exp_users') }}), 100000, 280000),
        (
            'mart_product_performance',
            (select count(*) from {{ ref('mart_product_performance') }}),
            100,
            5000
        )
    ])
)

select * from counts
where n not between lo and hi
