from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404

from .models import Folder, Image
from .preview_health import preview_files_exist
from .search import apply_match_reasons, hybrid_search, find_near_duplicates, get_visual_cluster


def serialize_image(img: Image) -> dict[str, Any]:
    return {
        "id": str(img.id),
        "filename": img.filename,
        "path": img.path,
        "file_ext": img.file_ext or img.ext or "",
        "mime_type": img.mime_type or "",
        "customer_name": img.customer_name or "",
        "project_name": img.project_name or "",
        "job_type": img.job_type or "",
        "probable_job_number": img.probable_job_number or "",
        "relative_dir": img.relative_dir or "",
        "preview_status": img.preview_status,
        "preview_exists": preview_files_exist(img),
        "metadata_status": img.metadata_status,
        "text_status": img.text_status,
        "embedding_status": img.embedding_status,
        "duplicate_group": img.duplicate_group or "",
        "is_primary_duplicate": bool(img.is_primary_duplicate),
        "visual_cluster_id": img.visual_cluster_id or "",
        "near_duplicate_count": img.near_duplicate_count,
        "similar_image_count": img.similar_image_count,
        "folder_id": img.folder_id,
        "folder_name": img.folder.name if img.folder_id else "",
        "width": img.width,
        "height": img.height,
        "captured_at": img.captured_at.isoformat() if img.captured_at else None,
        "mtime": img.mtime.isoformat() if img.mtime else None,
        "sha256": img.sha256 or "",
    }


def serialize_folder(folder: Folder) -> dict[str, Any]:
    return {
        "id": folder.id,
        "root_id": folder.root_id,
        "parent_id": folder.parent_id,
        "name": folder.name,
        "path": folder.path,
        "rel_path": folder.rel_path,
        "depth": folder.depth,
        "file_count": folder.file_count,
        "image_count": folder.image_count,
        "has_children": folder.has_children,
        "customer_name": folder.customer_name or "",
        "probable_job_number": folder.probable_job_number or "",
        "preview_image_id": str(folder.preview_image_id) if folder.preview_image_id else None,
    }


def get_image_or_404(image_id: str) -> Image:
    return get_object_or_404(Image.objects.select_related("folder", "root"), id=image_id)


def get_folder_or_404(folder_id: int) -> Folder:
    return get_object_or_404(Folder.objects.select_related("parent", "root", "preview_image"), id=folder_id)


def search_archive(query: str, *, folder_id: int | None = None, page: int = 1, per_page: int = 24) -> dict[str, Any]:
    query = (query or "").strip()
    rows: list[dict[str, Any]] = []
    if query:
        rows = hybrid_search(query, limit=max(per_page * 3, 72), folder_id=folder_id)

    ids = [row.get("point_id") for row in rows if row.get("point_id")]
    image_map = {
        str(img.id): img
        for img in Image.objects.filter(id__in=ids).select_related("folder")
    }

    hydrated = []
    for row in rows:
        pid = str(row.get("point_id"))
        img = image_map.get(pid)
        if not img:
            continue
        hydrated.append(img)

    reason_rows = apply_match_reasons([
        {"id": str(img.id), "filename": img.filename, "path": img.path, "image": img}
        for img in hydrated
    ], query, "hybrid")
    reasons = {str(row["id"]): row.get("match_labels", []) for row in reason_rows}

    payload = []
    for img in hydrated:
        row = serialize_image(img)
        row["match_reasons"] = reasons.get(str(img.id), [])
        payload.append(row)

    paginator = Paginator(payload, per_page)
    page_obj = paginator.get_page(page)
    return {
        "query": query,
        "folder_id": folder_id,
        "count": paginator.count,
        "num_pages": paginator.num_pages,
        "page": page_obj.number,
        "results": list(page_obj.object_list),
    }


def image_detail_payload(image_id: str) -> dict[str, Any]:
    img = get_image_or_404(image_id)
    payload = serialize_image(img)
    payload["extracted_text"] = (img.extracted_text or img.text or "")[:4000]
    payload["open_folder_path"] = img.folder.path if img.folder_id else img.relative_dir
    payload["same_folder"] = [
        serialize_image(other)
        for other in Image.objects.filter(folder_id=img.folder_id).exclude(id=img.id).order_by("filename")[:24]
    ] if img.folder_id else []
    payload["duplicate_group_items"] = [
        serialize_image(other)
        for other in Image.objects.filter(duplicate_group=img.duplicate_group).exclude(id=img.id).order_by("filename")[:24]
    ] if img.duplicate_group else []
    return payload


def image_similar_payload(image_id: str) -> dict[str, Any]:
    img = get_image_or_404(image_id)
    near_ids = [str(row.get("point_id")) for row in find_near_duplicates(str(img.id), limit=24)]
    cluster_ids = [str(row.get("point_id")) for row in get_visual_cluster(str(img.id), limit=24)]
    seen = {str(img.id)}
    similar = []
    for qset_ids, label in [(near_ids, "near_duplicate"), (cluster_ids, "cluster")]:
        for other in Image.objects.filter(id__in=qset_ids):
            if str(other.id) in seen:
                continue
            seen.add(str(other.id))
            row = serialize_image(other)
            row["relationship"] = label
            similar.append(row)
    return {"item": serialize_image(img), "results": similar}


def folder_detail_payload(folder_id: int) -> dict[str, Any]:
    folder = get_folder_or_404(folder_id)
    children = [serialize_folder(child) for child in Folder.objects.filter(parent_id=folder.id).select_related("preview_image").order_by("name")]
    images = [serialize_image(img) for img in Image.objects.filter(folder_id=folder.id).select_related("folder").order_by("filename")[:100]]
    breadcrumbs = []
    cursor = folder
    while cursor:
        breadcrumbs.append(serialize_folder(cursor))
        cursor = cursor.parent
    breadcrumbs.reverse()
    return {"folder": serialize_folder(folder), "children": children, "images": images, "breadcrumbs": breadcrumbs}


def folder_story_payload(folder_id: int) -> dict[str, Any]:
    folder = get_folder_or_404(folder_id)
    qs = Image.objects.filter(folder_id=folder.id)
    ext_counts = list(qs.values("file_ext").annotate(total=Count("id")).order_by("-total", "file_ext")[:10])
    status = {
        "preview_failed": qs.filter(preview_status="failed").count(),
        "preview_missing": qs.filter(Q(preview_status="pending") | Q(preview_status="failed") | Q(preview_status="unsupported")).count(),
        "metadata_failed": qs.filter(metadata_status="failed").count(),
        "duplicates": qs.exclude(duplicate_group="").count(),
        "clustered": qs.exclude(visual_cluster_id="").count(),
    }
    customers = list(qs.exclude(customer_name="").values("customer_name").annotate(total=Count("id")).order_by("-total", "customer_name")[:10])
    jobs = list(qs.exclude(probable_job_number="").values("probable_job_number").annotate(total=Count("id")).order_by("-total", "probable_job_number")[:10])
    return {
        "folder": serialize_folder(folder),
        "status": status,
        "file_types": ext_counts,
        "customers": customers,
        "jobs": jobs,
    }


def customer_payload(customer_name: str) -> dict[str, Any]:
    qs = Image.objects.filter(customer_name__iexact=customer_name).select_related("folder")
    jobs = list(qs.exclude(probable_job_number="").values("probable_job_number").annotate(total=Count("id")).order_by("-total", "probable_job_number")[:50])
    return {
        "customer": customer_name,
        "count": qs.count(),
        "jobs": jobs,
        "results": [serialize_image(img) for img in qs.order_by("-mtime", "filename")[:200]],
    }


def job_payload(job_number: str) -> dict[str, Any]:
    qs = Image.objects.filter(probable_job_number=job_number).select_related("folder")
    by_folder = list(qs.values("folder_id", "folder__name", "relative_dir").annotate(total=Count("id")).order_by("-total", "relative_dir")[:50])
    return {
        "job": job_number,
        "count": qs.count(),
        "folders": by_folder,
        "results": [serialize_image(img) for img in qs.order_by("-mtime", "filename")[:200]],
    }


def timeline_payload() -> dict[str, Any]:
    buckets: dict[str, int] = defaultdict(int)
    for img in Image.objects.exclude(captured_at__isnull=True).only("captured_at")[:10000]:
        label = img.captured_at.strftime("%Y-%m")
        buckets[label] += 1
    return {"buckets": [{"label": k, "count": buckets[k]} for k in sorted(buckets.keys())]}


def archive_map_payload() -> dict[str, Any]:
    return {
        "totals": {
            "images": Image.objects.count(),
            "folders": Folder.objects.count(),
            "customers": Image.objects.exclude(customer_name="").values("customer_name").distinct().count(),
            "jobs": Image.objects.exclude(probable_job_number="").values("probable_job_number").distinct().count(),
            "duplicate_groups": Image.objects.exclude(duplicate_group="").values("duplicate_group").distinct().count(),
            "clusters": Image.objects.exclude(visual_cluster_id="").values("visual_cluster_id").distinct().count(),
        },
        "file_types": list(Image.objects.values("file_ext").annotate(total=Count("id")).order_by("-total", "file_ext")[:25]),
    }
