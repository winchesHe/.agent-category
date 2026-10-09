from dd.commands import (
    aggregate_logs,
    get_dashboard,
    get_dependencies,
    get_trace,
    list_services,
    query_metrics,
    search_logs,
    search_spans,
)

ALL = [
    search_logs,
    aggregate_logs,
    get_trace,
    search_spans,
    get_dependencies,
    list_services,
    get_dashboard,
    query_metrics,
]
