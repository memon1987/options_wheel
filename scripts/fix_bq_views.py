#!/usr/bin/env python3
"""
Fix BigQuery views to properly extract JSON fields using JSON_VALUE()
"""

import re

def fix_json_field_references(sql_content):
    """Replace jsonPayload.field references with JSON_VALUE() calls"""

    # Pattern 1: CAST(jsonPayload.field AS TYPE) -> CAST(JSON_VALUE(jsonPayload.field) AS TYPE)
    sql_content = re.sub(
        r'CAST\(jsonPayload\.(\w+) AS (FLOAT64|INT64|BOOL)\)',
        r'CAST(JSON_VALUE(jsonPayload.\1) AS \2)',
        sql_content
    )

    # Pattern 2: jsonPayload.field (not already wrapped) -> JSON_VALUE(jsonPayload.field)
    # But NOT inside JSON_VALUE() calls we just added
    # This matches jsonPayload.field that is NOT preceded by JSON_VALUE( and NOT followed by AS
    sql_content = re.sub(
        r'(?<!JSON_VALUE\()jsonPayload\.(\w+)(?!\s+AS\s+(?:FLOAT64|INT64|BOOL))',
        r'JSON_VALUE(jsonPayload.\1)',
        sql_content
    )

    return sql_content

# Read the SQL file
with open('/Users/zmemon/options_wheel-1/docs/bigquery_views.sql', 'r') as f:
    sql_content = f.read()

# Fix the references
fixed_sql = fix_json_field_references(sql_content)

# Write back
with open('/Users/zmemon/options_wheel-1/docs/bigquery_views.sql', 'w') as f:
    f.write(fixed_sql)

print("Fixed all jsonPayload references to use JSON_VALUE()")
print("Views are now ready to be created in BigQuery")
