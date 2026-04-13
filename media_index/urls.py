"""
URL configuration for media_index project.
"""
from django.conf import settings
from django.views.static import serve
from django.contrib import admin
from django.urls import include, path, re_path

from indexer.api import thumb
from indexer.api_health import api_health_summary
from indexer.api_image import api_image_detail
from indexer.api_search import api_search
from indexer.api_similar import similar
from indexer.ui_views import (
    landing,
    login_view,
    logout_view,
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
    ui_rebuild_folder_index,
    ui_rebuild_folder_index_full,
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
    ui_pipeline_stage,
)
from indexer.views_documents import (
    document_approve,
    document_detail,
    document_inbox,
    document_needs_review,
    document_quick_edit,
    document_reprocess,
)
from indexer.views_mail import (
    email_detail,
    email_inbox,
    email_reprocess_documents,
)

urlpatterns = [
    path("", include("indexer.ops_urls")),
    path("admin/", admin.site.urls),

    # Public
    path("", landing, name="landing"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),

    # UI
    path("ui/", ui_home, name="ui_home"),
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
    path("ui/browse/folder/<int:folder_id>/rebuild/", ui_rebuild_folder_index, name="ui_rebuild_folder_index"),
    path("ui/browse/rebuild/", ui_rebuild_folder_index_full, name="ui_rebuild_folder_index_full"),
    path("ui/jobs/", ui_jobs, name="ui_jobs"),
    path("ui/jobs/<str:job_number>/", ui_job_detail, name="ui_job_detail"),
    path("ui/customers/", ui_customers, name="ui_customers"),
    path("ui/customers/<str:customer_name>/", ui_customer_detail, name="ui_customer_detail"),
    path("ui/duplicates/", ui_duplicates, name="ui_duplicates"),
    path("ui/duplicates/<str:group_id>/", ui_duplicate_group, name="ui_duplicate_group"),
    path("ui/clusters/", ui_clusters, name="ui_clusters"),
    path("ui/clusters/<str:cluster_id>/", ui_cluster_detail, name="ui_cluster_detail"),
    path("ui/health/folders/", ui_folder_health, name="ui_folder_health"),
    path("ui/health/folders/<int:folder_id>/<str:issue_code>/", ui_folder_issue_detail, name="ui_folder_issue_detail"),
    path("ui/pipeline/<str:stage>/", ui_pipeline_stage, name="ui_pipeline_stage"),

    # Document + email UI
    path("ui/documents/", document_inbox, name="document_inbox"),
    path("ui/documents/<int:pk>/", document_detail, name="document_detail"),
    path("ui/documents/<int:pk>/edit/", document_quick_edit, name="document_quick_edit"),
    path("ui/documents/<int:pk>/approve/", document_approve, name="document_approve"),
    path("ui/documents/<int:pk>/needs-review/", document_needs_review, name="document_needs_review"),
    path("ui/documents/<int:pk>/reprocess/", document_reprocess, name="document_reprocess"),
    path("ui/mail/", email_inbox, name="email_inbox"),
    path("ui/mail/<int:pk>/", email_detail, name="email_detail"),
    path("ui/mail/<int:pk>/reprocess-documents/", email_reprocess_documents, name="email_reprocess_documents"),

    # API
    path("api/health/summary/", api_health_summary, name="api_health_summary"),
    path("api/search/", api_search, name="api_search"),
    path("api/image/<uuid:image_id>/", api_image_detail, name="api_image_detail"),
    path("api/image/<uuid:image_id>/similar/", similar, name="api_similar"),
    path("api/thumb/<uuid:image_id>/", thumb, name="api_thumb"),
    path("api/archive/", include("indexer.api_urls")),
]

# 🔥 MEDIA SERVING (works in prod without nginx)
urlpatterns += [
    re_path(
        r"^media/(?P<path>.*)$",
        serve,
        {"document_root": settings.MEDIA_ROOT},
    ),
]
