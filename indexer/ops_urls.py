from django.urls import path

from .ops_views import run_dashboard_ops_action

app_name = "indexer_ops"

urlpatterns = [
    path("ui/ops/action/", run_dashboard_ops_action, name="run_dashboard_ops_action"),
]