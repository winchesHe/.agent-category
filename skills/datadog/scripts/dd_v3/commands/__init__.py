from dd_v3.commands import (
    compare_logs,
    datastore_items,
    datastores,
    dashboard_lists,
    dashboards,
    error_summary,
    log_context,
    log_patterns,
    log_services,
    monitors,
    scan_slow_sql,
    trace_logs,
)

ALL = [
    scan_slow_sql,
    monitors,
    trace_logs,
    log_context,
    error_summary,
    compare_logs,
    log_patterns,
    log_services,
    dashboards,
    dashboard_lists,
    datastores,
    datastore_items,
]
