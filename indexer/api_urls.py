from django.urls import path

from .api_views import (
    api_archive_customer_detail,
    api_archive_folder_detail,
    api_archive_folder_story,
    api_archive_item_detail,
    api_archive_item_similar,
    api_archive_job_detail,
    api_archive_map,
    api_archive_search,
    api_archive_timeline,
)

app_name = "archive_api"

urlpatterns = [
    path("search/", api_archive_search, name="search"),
    path("items/<uuid:image_id>/", api_archive_item_detail, name="item_detail"),
    path("items/<uuid:image_id>/similar/", api_archive_item_similar, name="item_similar"),
    path("folders/<int:folder_id>/", api_archive_folder_detail, name="folder_detail"),
    path("folders/<int:folder_id>/story/", api_archive_folder_story, name="folder_story"),
    path("customers/<str:customer_name>/", api_archive_customer_detail, name="customer_detail"),
    path("jobs/<str:job_number>/", api_archive_job_detail, name="job_detail"),
    path("timeline/", api_archive_timeline, name="timeline"),
    path("archive-map/", api_archive_map, name="archive_map"),
]
