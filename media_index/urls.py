"""
URL configuration for media_index project.
"""
from django.contrib import admin
from django.urls import include, path

from indexer.api import thumb
from indexer.api_health import api_health_summary
from indexer.api_image import api_image_detail
from indexer.api_search import api_search
from indexer.api_similar import similar
from indexer.ui_views import (
    ui_browse_folder,
    ui_browse_root,
    ui_cluster_detail,
    ui_clusters,
    ui_collections,
    ui_customer_detail,
    ui_customers,
    ui_duplicate_group,
    ui_duplicates,
    ui_folder_health,
    ui_folder_issue_detail,
    ui_health,
    ui_home,
    ui_item,
    ui_job_detail,
    ui_jobs,
    ui_requeue_stage,
    ui_retry_index,
    ui_retry_preview,
    ui_search,
    ui_similar,
    ui_status,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", ui_home, name="ui_home"),
    path("ui/", ui_home, name="ui_home_alt"),
    path("ui/search/", ui_search, name="ui_search"),
    path("ui/item/<uuid:image_id>/", ui_item, name="ui_item"),
    path("ui/similar/<uuid:image_id>/", ui_similar, name="ui_similar"),
    path("ui/collections/", ui_collections, name="ui_collections"),
    path("ui/status/", ui_status, name="ui_status"),
    path("ui/health/", ui_health, name="ui_health"),
    path("ui/retry-preview/<uuid:image_id>/", ui_retry_preview, name="ui_retry_preview"),
    path("ui/retry-index/<uuid:image_id>/", ui_retry_index, name="ui_retry_index"),
    path("ui/requeue-stage/<str:stage>/", ui_requeue_stage, name="ui_requeue_stage"),
    path("ui/browse/", ui_browse_root, name="ui_browse_root"),
    path("ui/browse/folder/<int:folder_id>/", ui_browse_folder, name="ui_browse_folder"),
    path("ui/jobs/", ui_jobs, name="ui_jobs"),
    path("ui/jobs/<str:job_number>/", ui_job_detail, name="ui_job_detail"),
    path("ui/customers/", ui_customers, name="ui_customers"),
    path("ui/customers/<str:customer>/", ui_customer_detail, name="ui_customer_detail"),
    path("ui/duplicates/", ui_duplicates, name="ui_duplicates"),
    path("ui/duplicates/<str:group>/", ui_duplicate_group, name="ui_duplicate_group"),
    path("ui/clusters/", ui_clusters, name="ui_clusters"),
    path("ui/clusters/<str:cluster_id>/", ui_cluster_detail, name="ui_cluster_detail"),
    path("ui/health/folders/", ui_folder_health, name="ui_folder_health"),
    path("ui/health/folders/<int:folder_id>/<str:issue_code>/", ui_folder_issue_detail, name="ui_folder_issue_detail"),
    path("api/health/summary/", api_health_summary, name="api_health_summary"),
    path("api/search/", api_search, name="api_search"),
    path("api/image/<uuid:image_id>/", api_image_detail, name="api_image_detail"),
    path("api/image/<uuid:image_id>/similar/", similar, name="api_similar"),
    path("api/thumb/<uuid:image_id>/", thumb, name="api_thumb"),
    path("api/archive/", include("indexer.api_urls")),
]
