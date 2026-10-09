-- Week 0 of every cohort is the week users were acquired in: retention must be 100%.
select * from {{ ref('mart_cohort_retention') }}
where week_number = 0 and abs(retention - 1) > 1e-9
