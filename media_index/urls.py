"""
URL configuration for media_index project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

from indexer.api import thumb
from indexer.api_health import api_health_summary
from indexer.api_image import api_image_detail
from indexer.api_search import api_search
from indexer.api_similar import similar
from indexer.ui_views import (
    ui_collections,
    ui_health,
    ui_home,
    ui_item,
    ui_retry_index,
    ui_retry_preview,
    ui_search,
    ui_similar,
    ui_status,
    ui_requeue_stage,
    ui_browse_root,
    ui_browse_folder,
    #api_folder_children,
    ui_jobs,
    ui_job_detail,
    ui_customers,
    ui_customer_detail,
    ui_duplicates,
    ui_duplicate_group,
    ui_clusters,
    ui_cluster_detail,
    ui_folder_health,
    ui_folder_issue_detail,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),

    path("api/search", api_search),
    path("api/thumb/<uuid:image_id>", thumb),
    path("api/similar/<uuid:image_id>", similar),
    path("api/image/<uuid:image_id>", api_image_detail),
    path("api/health/summary", api_health_summary),

    path("ui/", ui_home),
    path("ui/search/", ui_search),
    path("ui/item/<uuid:image_id>/", ui_item),
    path("ui/status/", ui_status, name="ui_status"),
    path("ui/similar/<uuid:image_id>/", ui_similar),
    path("ui/health/", ui_health),
    path("ui/collections/", ui_collections),
    path("ui/retry-preview/<uuid:image_id>/", ui_retry_preview),
    path("ui/retry-index/<uuid:image_id>/", ui_retry_index),
    path("ui/requeue/<str:stage>/", ui_requeue_stage, name="ui_requeue_stage"),

    path("ui/browse/", ui_browse_root, name="ui_browse_root"),
    path("ui/browse/folder/<int:folder_id>/", ui_browse_folder, name="ui_browse_folder"),
    #path("api/folders/<int:folder_id>/children/", api_folder_children, name="api_folder_children")

    path("ui/jobs/", ui_jobs, name="ui_jobs"),
    path("ui/jobs/<str:job_number>/", ui_job_detail, name="ui_job_detail"),
    path("ui/customers/", ui_customers, name="ui_customers"),
    path("ui/customers/<str:customer_name>/", ui_customer_detail, name="ui_customer_detail"),
    path("ui/duplicates/", ui_duplicates, name="ui_duplicates"),
    path("ui/duplicates/<str:group_id>/", ui_duplicate_group, name="ui_duplicate_group"),
    path("ui/clusters/", ui_clusters, name="ui_clusters"),
    path("ui/clusters/<str:cluster_id>/", ui_cluster_detail, name="ui_cluster_detail"),
    path("ui/health/folders/", ui_folder_health, name="ui_folder_health"),
    path("ui/health/folders/<int:folder_id>/<str:issue>/", ui_folder_issue_detail, name="ui_folder_issue_detail"),
]
