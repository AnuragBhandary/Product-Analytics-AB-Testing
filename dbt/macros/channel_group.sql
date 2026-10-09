{# Default-channel-style grouping. The obfuscated sample hides some values as <Other>, and
   GA deleted others; those stay visible as their own groups rather than being guessed. #}
{% macro channel_group(medium, source) -%}
    case
        when {{ medium }} is null then 'Unknown'
        when {{ medium }} = 'organic' then 'Organic Search'
        when {{ medium }} = 'cpc' then 'Paid Search'
        when {{ medium }} = '(none)' and {{ source }} = '(direct)' then 'Direct'
        when {{ medium }} = 'referral' then 'Referral'
        when {{ medium }} = '(data deleted)' then 'Data deleted'
        when {{ medium }} = '<Other>' then 'Other (obfuscated)'
        else 'Other'
    end
{%- endmacro %}
