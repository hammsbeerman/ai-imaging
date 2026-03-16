from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET

from .api_helpers import render_api_response
from .archive_queries import (
    archive_map_payload,
    customer_payload,
    folder_detail_payload,
    folder_story_payload,
    image_detail_payload,
    image_similar_payload,
    job_payload,
    search_archive,
    timeline_payload,
)


@login_required
@require_GET
def api_archive_search(request):
    context = search_archive(
        request.GET.get("q", ""),
        folder_id=request.GET.get("folder_id") or None,
        page=int(request.GET.get("page") or 1),
        per_page=int(request.GET.get("per_page") or 24),
    )
    return render_api_response(request, "indexer/api/search_results.html", context)


@login_required
@require_GET
def api_archive_item_detail(request, image_id: str):
    context = image_detail_payload(image_id)
    return render_api_response(request, "indexer/api/item_detail.html", context)


@login_required
@require_GET
def api_archive_item_similar(request, image_id: str):
    context = image_similar_payload(image_id)
    return render_api_response(request, "indexer/api/item_similar.html", context)


@login_required
@require_GET
def api_archive_folder_detail(request, folder_id: int):
    context = folder_detail_payload(folder_id)
    return render_api_response(request, "indexer/api/folder_detail.html", context)


@login_required
@require_GET
def api_archive_folder_story(request, folder_id: int):
    context = folder_story_payload(folder_id)
    return render_api_response(request, "indexer/api/folder_story.html", context)


@login_required
@require_GET
def api_archive_customer_detail(request, customer_name: str):
    context = customer_payload(customer_name)
    return render_api_response(request, "indexer/api/customer_detail.html", context)


@login_required
@require_GET
def api_archive_job_detail(request, job_number: str):
    context = job_payload(job_number)
    return render_api_response(request, "indexer/api/job_detail.html", context)


@login_required
@require_GET
def api_archive_timeline(request):
    context = timeline_payload()
    return render_api_response(request, "indexer/api/timeline.html", context)


@login_required
@require_GET
def api_archive_map(request):
    context = archive_map_payload()
    return render_api_response(request, "indexer/api/archive_map.html", context)
