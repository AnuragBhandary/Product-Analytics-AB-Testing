{# Pull one key out of GA4's event_params array. #}
{% macro ga4_param(key, type='string') -%}
    (select ep.value.{{ type }}_value from unnest(event_params) as ep where ep.key = '{{ key }}')
{%- endmacro %}
