from django.urls import path

from .ops_views import ops_status_partial, run_dashboard_ops_action

app_name = "indexer_ops"

urlpatterns = [
    path("ui/ops/action/", run_dashboard_ops_action, name="run_dashboard_ops_action"),
    path("ui/ops/status/", ops_status_partial, name="ops_status_partial"),
]