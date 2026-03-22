import os
from pathlib import Path
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import models
from django.db.models import Q, Count, Min, Max, Case, When, IntegerField
from django.core.paginator import Paginator
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from urllib.parse import quote

from indexer.models import (
    Folder,
    Image,
    IndexerSettings,
    ScanDir,
    TaskLog,
    UserAccessRoot,
    ProcessingStatus,
    PreviewStatus,
    ArchiveStats,
    FolderHealthSnapshot,
    QueueHealthSnapshot,
)
from indexer.open_links import build_smb_folder, build_unc_folder, folder_rel
from indexer.tasks_preview import process_preview_task
from indexer.tasks_text import extract_text_task
from indexer.tasklog import log
from indexer.tasks_embedding import embed_image_task
from indexer.tasks_metadata import extract_metadata_task
from indexer.services.health_service import (
    get_health_summary,
    get_recent_errors,
    get_top_error_reasons,
)
from indexer.services.preview_health_service import (
    get_mount_health,
    count_missing_ok_previews,
    get_preview_error_buckets,
    get_unsupported_ext_buckets,
)
from indexer.services.queue_health_service import (
    get_scan_queue_counts,
    get_preview_queue_counts,
    get_text_queue_counts,
    get_metadata_queue_counts,
    get_embedding_queue_counts,
    get_recent_tasklog_rows,
    get_stuck_processing_counts,
    get_top_pipeline_errors,
    get_recent_task_metrics,
)
from indexer.search import (
    discover_clusters,
    embed_uploaded_image,
    find_near_duplicates,
    get_visual_cluster,
    hybrid_search,
    qdrant_get_vector,
    qdrant_search,
    search_by_folder,
    search_text,
    detect_match_reasons,
    apply_match_reasons
)
from indexer.services.preview_health import (
    get_preview_drift,
    get_preview_drift_count,
)
from indexer.models_documents import Document

from .ops_actions import collect_ops_status


def _allowed_root_ids(user) -> set[int]:
    if not getattr(user, "is_authenticated", False):
        return set()

    if getattr(user, "is_superuser", False):
        return set(
            Image.objects.exclude(root__isnull=True)
            .values_list("root_id", flat=True)
            .distinct()
        )

    return set(
        UserAccessRoot.objects.filter(user_id=user.id)
        .values_list("root_id", flat=True)
    )


def _open_folder_links_for(img: Image, settings: IndexerSettings):
    if img.root_id and img.root:
        unc_base = img.root.open_folder_unc_base or settings.open_folder_unc_base
        smb_base = img.root.open_folder_smb_base or settings.open_folder_smb_base
        scan_base = img.root.scan_path_root
    else:
        unc_base = settings.open_folder_unc_base
        smb_base = settings.open_folder_smb_base
        scan_base = settings.scan_path

    rel_folder = folder_rel(scan_base, img.path)

    return {
        "open_folder_unc": build_unc_folder(unc_base, rel_folder) if unc_base else None,
        "open_folder_smb": build_smb_folder(smb_base, rel_folder) if smb_base else None,
    }


def _folder_breadcrumbs(folder: Folder):
    crumbs = []
    cur = folder
    while cur:
        crumbs.append(cur)
        cur = cur.parent
    return list(reversed(crumbs))


def _open_folder_links_for_folder(folder: Folder):
    if not folder.root_id or not folder.root:
        return {
            "open_folder_unc": None,
            "open_folder_smb": None,
        }

    unc_base = folder.root.open_folder_unc_base
    smb_base = folder.root.open_folder_smb_base
    rel_folder = (folder.rel_path or "").strip("/")

    return {
        "open_folder_unc": build_unc_folder(unc_base, rel_folder) if unc_base else None,
        "open_folder_smb": build_smb_folder(smb_base, rel_folder) if smb_base else None,
    }


def _cached_child_folders(folder_id: int, allowed_root_ids, ttl: int = 60):
    allowed_root_ids = sorted(set(allowed_root_ids))
    cache_key = f"browse:children:{folder_id}:{','.join(str(x) for x in allowed_root_ids)}"

    child_ids = cache.get(cache_key)
    if child_ids is None:
        child_ids = list(
            Folder.objects.filter(
                parent_id=folder_id,
                root_id__in=allowed_root_ids,
            )
            .order_by("name")
            .values_list("id", flat=True)
        )
        cache.set(cache_key, child_ids, ttl)

    return list(
        Folder.objects.filter(id__in=child_ids)
        .select_related("preview_image")
        .annotate(child_folder_count=Count("children", distinct=True))
        .order_by("name")
    )


def _folder_scope_prefix(folder: Folder) -> str:
    return (folder.rel_path or "").strip("/")


def _apply_folder_scope_qs(qs, folder: Folder):
    if not folder:
        return qs

    prefix = _folder_scope_prefix(folder)
    qs = qs.filter(root_id=folder.root_id)

    if not prefix:
        return qs

    return qs.filter(
        Q(relative_dir=prefix) |
        Q(relative_dir__startswith=prefix + "/")
    )


def _image_in_folder_scope(img: Image, folder: Folder) -> bool:
    if not folder:
        return True

    if img.root_id != folder.root_id:
        return False

    prefix = _folder_scope_prefix(folder)
    rel_dir = (img.relative_dir or "").strip("/")

    if not prefix:
        return True

    return rel_dir == prefix or rel_dir.startswith(prefix + "/")


def _filter_images_to_folder_scope(images, folder: Folder):
    if not folder:
        return images
    return [img for img in images if _image_in_folder_scope(img, folder)]


def _pct(n, total):
    if not total:
        return 0
    return round((n / total) * 100, 1)


def _folder_health_counts(folder_ids: list[int]) -> dict[int, dict[str, int]]:
    if not folder_ids:
        return {}

    rows = (
        Image.objects.filter(folder_id__in=folder_ids)
        .values("folder_id")
        .annotate(
            preview_failed_count=Count("id", filter=Q(preview_status="failed")),
            missing_preview_count=Count(
                "id",
                filter=Q(preview_status__in=["pending", "failed", "unsupported"])
            ),
            duplicate_count=Count("id", filter=Q(duplicate_group__gt="")),
        )
    )

    return {
        row["folder_id"]: {
            "preview_failed_count": row["preview_failed_count"],
            "missing_preview_count": row["missing_preview_count"],
            "duplicate_count": row["duplicate_count"],
        }
        for row in rows
    }


def _latest_for_scope(model, scope="global"):
    qs = model.objects.all()
    field_names = {f.name for f in model._meta.fields}

    if "scope" in field_names:
        qs = qs.filter(scope=scope)

    if "updated_at" in field_names:
        return qs.order_by("-updated_at").first()

    return qs.order_by("-id").first()


def _zero_archive_stats():
    return ArchiveStats(
        scope="global",
        total_files=0,
        indexed_files=0,
        preview_ok=0,
        preview_pending=0,
        preview_processing=0,
        preview_failed=0,
        preview_unsupported=0,
        text_ok=0,
        text_pending=0,
        text_processing=0,
        text_failed=0,
        text_skipped=0,
        text_native_pdf=0,
        text_ocr_image=0,
        text_high_conf=0,
        text_mid_conf=0,
        text_low_conf=0,
        metadata_ok=0,
        metadata_pending=0,
        metadata_processing=0,
        metadata_failed=0,
        metadata_skipped=0,
        embedding_ok=0,
        embedding_pending=0,
        embedding_processing=0,
        embedding_failed=0,
        embedding_skipped=0,
        duplicate_groups=0,
        duplicate_items=0,
    )


def _age_minutes(dt):
    if not dt:
        return None
    return int((timezone.now() - dt).total_seconds() // 60)


def _get_preview_url(img):
    for attr in ("preview_url", "thumb_url", "thumbnail_url"):
        value = getattr(img, attr, None)
        if callable(value):
            try:
                value = value()
            except Exception:
                value = None
        if value:
            return value

    rel_candidates = [
        getattr(img, "preview_rel_path", None),
        getattr(img, "thumb_rel_path", None),
        getattr(img, "thumbnail_rel_path", None),
        getattr(img, "thumb_path", None),
        getattr(img, "preview_path", None),
    ]
    rel_path = next((x for x in rel_candidates if x), None)
    if rel_path:
        rel_path = str(rel_path).lstrip("/")
        if rel_path.startswith("http://") or rel_path.startswith("https://") or rel_path.startswith("/"):
            return rel_path
        return f"/media/{rel_path}"

    return ""


@login_required
def ui_collections(request):
    clusters = discover_clusters()

    return render(
        request,
        "indexer/ui_collections.html",
        {
            "clusters": clusters,
        },
    )


@login_required
def ui_home(request):

    stats = _latest_for_scope(ArchiveStats, scope="global") or _zero_archive_stats()
    queue_snapshot = _latest_for_scope(QueueHealthSnapshot, scope="global")

    worst_folders = list(
        FolderHealthSnapshot.objects.filter(scope="global").order_by("rank")[:10]
    )

    total_files = stats.total_files or 0
    indexed = stats.indexed_files or 0

    preview_counts = {
        "ok": stats.preview_ok or 0,
        "pending_ready": stats.preview_pending or 0,
        "processing": stats.preview_processing or 0,
        "failed": stats.preview_failed or 0,
        "unsupported": stats.preview_unsupported or 0,
    }
    text_counts = {
        "ok": stats.text_ok or 0,
        "pending_ready": stats.text_pending or 0,
        "processing": stats.text_processing or 0,
        "failed": stats.text_failed or 0,
        "skipped": stats.text_skipped or 0,
    }
    metadata_counts = {
        "ok": stats.metadata_ok or 0,
        "pending_ready": stats.metadata_pending or 0,
        "processing": stats.metadata_processing or 0,
        "failed": stats.metadata_failed or 0,
        "skipped": stats.metadata_skipped or 0,
    }
    embedding_counts = {
        "ok": stats.embedding_ok or 0,
        "pending_ready": stats.embedding_pending or 0,
        "processing": stats.embedding_processing or 0,
        "failed": stats.embedding_failed or 0,
        "skipped": stats.embedding_skipped or 0,
    }

    text_quality = {
        "native_pdf": stats.text_native_pdf or 0,
        "ocr_image": stats.text_ocr_image or 0,
        "high_conf": stats.text_high_conf or 0,
        "mid_conf": stats.text_mid_conf or 0,
        "low_conf": stats.text_low_conf or 0,
    }

    graph_rows = [
        {
            "label": "Preview",
            "done": preview_counts["ok"],
            "ready": preview_counts["pending_ready"],
            "processing": preview_counts["processing"],
            "failed": preview_counts["failed"],
            "other": preview_counts["unsupported"],
            "done_pct": _pct(preview_counts["ok"], total_files),
            "ready_pct": _pct(preview_counts["pending_ready"], total_files),
            "processing_pct": _pct(preview_counts["processing"], total_files),
            "failed_pct": _pct(preview_counts["failed"], total_files),
            "other_pct": _pct(preview_counts["unsupported"], total_files),
            "other_label": "Unsupported",
        },
        {
            "label": "Text",
            "done": text_counts["ok"],
            "ready": text_counts["pending_ready"],
            "processing": text_counts["processing"],
            "failed": text_counts["failed"],
            "other": text_counts["skipped"],
            "done_pct": _pct(text_counts["ok"], total_files),
            "ready_pct": _pct(text_counts["pending_ready"], total_files),
            "processing_pct": _pct(text_counts["processing"], total_files),
            "failed_pct": _pct(text_counts["failed"], total_files),
            "other_pct": _pct(text_counts["skipped"], total_files),
            "other_label": "Skipped",
        },
        {
            "label": "Metadata",
            "done": metadata_counts["ok"],
            "ready": metadata_counts["pending_ready"],
            "processing": metadata_counts["processing"],
            "failed": metadata_counts["failed"],
            "other": metadata_counts["skipped"],
            "done_pct": _pct(metadata_counts["ok"], total_files),
            "ready_pct": _pct(metadata_counts["pending_ready"], total_files),
            "processing_pct": _pct(metadata_counts["processing"], total_files),
            "failed_pct": _pct(metadata_counts["failed"], total_files),
            "other_pct": _pct(metadata_counts["skipped"], total_files),
            "other_label": "Skipped",
        },
        {
            "label": "Embedding",
            "done": embedding_counts["ok"],
            "ready": embedding_counts["pending_ready"],
            "processing": embedding_counts["processing"],
            "failed": embedding_counts["failed"],
            "other": embedding_counts["skipped"],
            "done_pct": _pct(embedding_counts["ok"], total_files),
            "ready_pct": _pct(embedding_counts["pending_ready"], total_files),
            "processing_pct": _pct(embedding_counts["processing"], total_files),
            "failed_pct": _pct(embedding_counts["failed"], total_files),
            "other_pct": _pct(embedding_counts["skipped"], total_files),
            "other_label": "Skipped",
        },
    ]

    queue_summary = {
        "scan": getattr(queue_snapshot, "scan_pending_dirs", 0) if queue_snapshot else 0,
        "preview": getattr(queue_snapshot, "preview_pending", 0) if queue_snapshot else 0,
        "text": getattr(queue_snapshot, "text_pending", 0) if queue_snapshot else 0,
        "metadata": getattr(queue_snapshot, "metadata_pending", 0) if queue_snapshot else 0,
        "embedding": getattr(queue_snapshot, "embedding_pending", 0) if queue_snapshot else 0,
    }

    scan_queue = {
        "pending_dirs": getattr(queue_snapshot, "scan_pending_dirs", 0) if queue_snapshot else 0,
        "retrying_dirs": getattr(queue_snapshot, "scan_retrying_dirs", 0) if queue_snapshot else 0,
        "done_dirs": getattr(queue_snapshot, "scan_done_dirs", 0) if queue_snapshot else 0,
    }

    preview_queue = {
        "pending": getattr(queue_snapshot, "preview_pending", 0) if queue_snapshot else 0,
        "processing": getattr(queue_snapshot, "preview_processing", 0) if queue_snapshot else 0,
        "oldest_pending_at": getattr(queue_snapshot, "oldest_preview_pending_at", None) if queue_snapshot else None,
        "oldest_processing_at": getattr(queue_snapshot, "oldest_preview_processing_at", None) if queue_snapshot else None,
    }

    text_queue = {
        "pending": getattr(queue_snapshot, "text_pending", 0) if queue_snapshot else 0,
        "processing": getattr(queue_snapshot, "text_processing", 0) if queue_snapshot else 0,
        "oldest_pending_at": getattr(queue_snapshot, "oldest_text_pending_at", None) if queue_snapshot else None,
        "oldest_processing_at": getattr(queue_snapshot, "oldest_text_processing_at", None) if queue_snapshot else None,
    }

    metadata_queue = {
        "pending": getattr(queue_snapshot, "metadata_pending", 0) if queue_snapshot else 0,
        "processing": getattr(queue_snapshot, "metadata_processing", 0) if queue_snapshot else 0,
        "oldest_pending_at": getattr(queue_snapshot, "oldest_metadata_pending_at", None) if queue_snapshot else None,
        "oldest_processing_at": getattr(queue_snapshot, "oldest_metadata_processing_at", None) if queue_snapshot else None,
    }

    embedding_queue = {
        "pending": getattr(queue_snapshot, "embedding_pending", 0) if queue_snapshot else 0,
        "processing": getattr(queue_snapshot, "embedding_processing", 0) if queue_snapshot else 0,
        "oldest_pending_at": getattr(queue_snapshot, "oldest_embedding_pending_at", None) if queue_snapshot else None,
        "oldest_processing_at": getattr(queue_snapshot, "oldest_embedding_processing_at", None) if queue_snapshot else None,
    }

    stuck_processing = {
        "preview": getattr(queue_snapshot, "stuck_preview", 0) if queue_snapshot else 0,
        "text": getattr(queue_snapshot, "stuck_text", 0) if queue_snapshot else 0,
        "metadata": getattr(queue_snapshot, "stuck_metadata", 0) if queue_snapshot else 0,
        "embedding": getattr(queue_snapshot, "stuck_embedding", 0) if queue_snapshot else 0,
    }

    metric_task_names = [
        "rebuild_archive_stats_task",
        "rebuild_queue_health_snapshot_task",
        "rebuild_folder_health_snapshot_task",
        "queue_missing_previews_task",
        "queue_missing_text_task",
        "queue_missing_embeddings_task",
        "queue_missing_metadata_task",
        "reset_stale_processing_task",
        "reset_stale_preview_processing_task",
    ]
    recent_metrics = get_recent_task_metrics(metric_task_names, limit=24)

    latest_metric_by_task = {}
    for row in recent_metrics:
        latest_metric_by_task.setdefault(row.task_name, row)

    runtime_labels = {
        "rebuild_archive_stats_task": "Archive stats rebuild",
        "rebuild_queue_health_snapshot_task": "Queue snapshot rebuild",
        "rebuild_folder_health_snapshot_task": "Folder health rebuild",
        "queue_missing_previews_task": "Preview queue batch",
        "queue_missing_text_task": "Text queue batch",
        "queue_missing_embeddings_task": "Embedding queue batch",
        "queue_missing_metadata_task": "Metadata queue batch",
        "reset_stale_processing_task": "Recovery reset",
        "reset_stale_preview_processing_task": "Preview stale reset",
    }

    task_runtime_rows = []
    for task_name, label in runtime_labels.items():
        metric = latest_metric_by_task.get(task_name)
        task_runtime_rows.append(
            {
                "label": label,
                "task_name": task_name,
                "status": getattr(metric, "status", "—") if metric else "—",
                "duration_ms": getattr(metric, "duration_ms", None) if metric else None,
                "finished_at": getattr(metric, "finished_at", None) if metric else None,
            }
        )

    recent_preview_qs = (
        Image.objects
        .filter(preview_status=PreviewStatus.OK)
        .order_by("-preview_created_at", "-updated_at")[:5]
    )

    recent_previews = []
    for img in recent_preview_qs:
        recent_previews.append(
            {
                "id": img.id,
                "filename": getattr(img, "filename", "") or "",
                "display_time": getattr(img, "preview_created_at", None) or getattr(img, "updated_at", None),
                "preview_status": getattr(img, "preview_status", ""),
                "preview_url": _get_preview_url(img),
                "path": getattr(img, "path", "") or "",
            }
        )

    doc_stats = {
        "pending": Document.objects.filter(review_status=Document.REVIEW_PENDING).count(),
        "approved": Document.objects.filter(review_status=Document.REVIEW_APPROVED).count(),
        "errors": Document.objects.filter(sync_status=Document.SYNC_ERROR).count(),
        "duplicates": Document.objects.filter(is_duplicate=True).count(),
    }

    try:
        mount_health = get_mount_health()
    except Exception:
        mount_health = {
            "path": "",
            "exists": False,
            "readable": False,
            "writable": False,
            "healthy": False,
        }

    stats_updated_at = getattr(stats, "updated_at", None)
    queue_snapshot_updated_at = getattr(queue_snapshot, "updated_at", None)

    system_signals = {
        "missing_previews": 0,
        "mount_ok": mount_health.get("healthy", False),
        "stats_stale_minutes": _age_minutes(stats_updated_at),
        "queue_stale_minutes": _age_minutes(queue_snapshot_updated_at),
    }

    context = {
        "total_files": total_files,
        "indexed_files": stats.indexed_files or 0,
        "duplicate_groups": stats.duplicate_groups or 0,
        "duplicate_items": stats.duplicate_items or 0,
        "text_quality": text_quality,
        "graph_rows": graph_rows,
        "mount_health": mount_health,
        "missing_ok_previews": 0,
        "preview_error_buckets": [],
        "system_signals": system_signals,
        "unsupported_ext_buckets": [],
        "scan_queue": scan_queue,
        "preview_queue": preview_queue,
        "queue_summary": queue_summary,
        "text_queue": text_queue,
        "metadata_queue": metadata_queue,
        "embedding_queue": embedding_queue,
        "stuck_processing": stuck_processing,
        "top_errors": [],
        "task_runtime_rows": task_runtime_rows,
        "worst_folders": worst_folders,
        "stats_updated_at": stats_updated_at,
        "queue_snapshot_updated_at": queue_snapshot_updated_at,
        "recent_previews": recent_previews,
        "doc_stats": doc_stats,
        "preview_complete": stats.preview_ok or 0,
        "text_complete": stats.text_ok or 0,
        "metadata_complete": stats.metadata_ok or 0,

    }

    return render(request, "indexer/ui_home.html", context)



@login_required
def ui_search(request):
    settings = IndexerSettings.load()
    allowed = _allowed_root_ids(request.user)

    q = (request.GET.get("q") or "").strip()
    limit = int(request.GET.get("limit") or 50)
    mode = (request.GET.get("mode") or "hybrid").strip().lower()

    results = []
    source_img = None

    folder_id = request.GET.get("folder_id")
    search_folder = None

    if folder_id:
        search_folder = get_object_or_404(
            Folder.objects.select_related("root"),
            id=folder_id,
            root_id__in=allowed,
        )

    def folder_scope_prefix(folder: Folder) -> str:
        return (folder.rel_path or "").strip("/")

    def apply_folder_scope_qs(qs, folder: Folder | None):
        if not folder:
            return qs

        prefix = folder_scope_prefix(folder)
        qs = qs.filter(root_id=folder.root_id)

        if not prefix:
            return qs

        return qs.filter(
            Q(relative_dir=prefix) |
            Q(relative_dir__startswith=prefix + "/")
        )

    def image_in_folder_scope(img: Image, folder: Folder | None) -> bool:
        if not folder:
            return True

        if img.root_id != folder.root_id:
            return False

        prefix = folder_scope_prefix(folder)
        rel_dir = (img.relative_dir or "").strip("/")

        if not prefix:
            return True

        return rel_dir == prefix or rel_dir.startswith(prefix + "/")

    def filter_images_to_folder_scope(images, folder: Folder | None):
        if not folder:
            return images
        return [img for img in images if image_in_folder_scope(img, folder)]

    def hydrate_hits(hits, exclude_id=None):
        point_ids = [str(h.get("point_id")) for h in hits if h.get("point_id")]

        qs = Image.objects.select_related("root").filter(id__in=point_ids)
        if not request.user.is_superuser and allowed:
            qs = qs.filter(root_id__in=allowed)

        img_map = {str(i.id): i for i in qs}

        hydrated = []
        for h in hits:
            iid = str(h.get("point_id"))
            if not iid:
                continue
            if exclude_id and iid == str(exclude_id):
                continue

            img = img_map.get(iid)
            if not img:
                continue

            img.score = h.get("score")
            hydrated.append(img)

        return filter_images_to_folder_scope(hydrated, search_folder)

    if request.method == "POST" and request.FILES.get("image"):
        mode = "similar"
        limit = int(request.POST.get("limit") or limit)

        vec = embed_uploaded_image(request.FILES["image"])
        hits = qdrant_search(vec, limit=limit)
        results = hydrate_hits(hits)

    elif q and mode == "semantic":
        hits = search_text(q, limit=limit, folder=search_folder)
        results = hydrate_hits(hits)

    elif q and mode == "hybrid":
        hits = hybrid_search(q, limit=limit, folder=search_folder)
        results = hydrate_hits(hits)

    elif mode == "similar_existing":
        source = get_object_or_404(
            Image.objects.select_related("root"),
            id=request.GET.get("id"),
        )
        source_img = source

        if not request.user.is_superuser and allowed and source.root_id not in allowed:
            raise Http404("Not found")

        vector = qdrant_get_vector(str(source.id))
        if vector:
            hits = qdrant_search(vector, limit=limit)
            results = hydrate_hits(hits, exclude_id=source.id)

    elif mode == "duplicates":
        source = get_object_or_404(
            Image.objects.select_related("root"),
            id=request.GET.get("id"),
        )
        source_img = source

        if not request.user.is_superuser and allowed and source.root_id not in allowed:
            raise Http404("Not found")

        hits = find_near_duplicates(str(source.id), limit=limit)
        results = hydrate_hits(hits)

    elif mode == "cluster":
        source = get_object_or_404(
            Image.objects.select_related("root"),
            id=request.GET.get("id"),
        )
        source_img = source

        if not request.user.is_superuser and allowed and source.root_id not in allowed:
            raise Http404("Not found")

        hits = get_visual_cluster(str(source.id), limit=limit)
        results = hydrate_hits(hits)

    elif mode == "folder":
        path = (request.GET.get("path") or "").strip()
        hits = search_by_folder(path, limit=limit, folder=search_folder)
        results = hydrate_hits(hits)

    elif q and mode == "db":
        qs = Image.objects.select_related("root")

        if not request.user.is_superuser and allowed:
            qs = qs.filter(root_id__in=allowed)

        qs = apply_folder_scope_qs(qs, search_folder)

        qs = qs.filter(
            Q(filename__icontains=q)
            | Q(path__icontains=q)
            | Q(text__icontains=q)
            | Q(extracted_text__icontains=q)
            | Q(folder_tokens__icontains=q)
            | Q(customer_name__icontains=q)
            | Q(job_type__icontains=q)
            | Q(probable_job_number__icontains=q)
        )

        results = list(qs.order_by("-created")[:limit])

    results = apply_match_reasons(results, q, mode)

    ctx = {
        "q": q,
        "limit": limit,
        "results": results,
        "mode": mode,
        "settings": settings,
        "search_folder": search_folder,
        "source_img": source_img if mode in {"similar_existing", "duplicates", "cluster"} else None,
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "indexer/partials/search_results.html", ctx)

    return render(request, "indexer/ui_search.html", ctx)


@login_required
def ui_item(request, image_id):
    allowed = _allowed_root_ids(request.user)
    settings_obj = IndexerSettings.load()

    img = get_object_or_404(
        Image.objects.select_related("root", "folder").prefetch_related(
            "asset_links__linked_image",
            "used_in_documents__parent",
        ),
        id=image_id,
    )

    if img.root_id and allowed and img.root_id not in allowed and not request.user.is_superuser:
        return render(request, "indexer/ui_not_allowed.html", status=404)

    item_path = img.path or ""
    item_dir = str(Path(item_path).parent) if item_path else ""
    item_stem = Path(item_path).stem if item_path else ""
    folder_prefix = item_dir.rstrip("/\\") + os.sep if item_dir else ""

    related_same_folder = []
    sibling_job_files = []

    if item_dir:
        same_folder_qs = (
            Image.objects.select_related("root", "folder")
            .filter(path__startswith=folder_prefix)
            .exclude(id=img.id)
            .order_by("filename")[:50]
        )

        if not request.user.is_superuser and allowed:
            same_folder_qs = same_folder_qs.filter(Q(root_id__in=allowed) | Q(root__isnull=True))

        related_same_folder = list(same_folder_qs)

    if item_dir and item_stem:
        sibling_candidates = (
            Image.objects.select_related("root", "folder")
            .filter(path__startswith=folder_prefix)
            .exclude(id=img.id)
            .order_by("filename")[:100]
        )

        if not request.user.is_superuser and allowed:
            sibling_candidates = sibling_candidates.filter(Q(root_id__in=allowed) | Q(root__isnull=True))

        exact_stem = []
        loose_stem = []

        for other in sibling_candidates:
            try:
                other_stem = Path(other.path).stem
            except Exception:
                other_stem = ""

            if not other_stem:
                continue

            if other_stem.lower() == item_stem.lower():
                exact_stem.append(other)
            elif other_stem.lower().startswith(item_stem.lower()):
                loose_stem.append(other)

        seen = set()
        ordered = []
        for other in exact_stem + loose_stem:
            if other.id not in seen:
                seen.add(other.id)
                ordered.append(other)

        sibling_job_files = ordered[:25]

    links = img.asset_links.select_related("linked_image").all().order_by("source", "linked_path")
    used_in = img.used_in_documents.select_related("parent").all().order_by("-created_at")

    open_links = _open_folder_links_for(img, settings_obj)

    customer_url = None
    if img.customer_name:
        customer_url = f"/ui/customers/{quote(img.customer_name)}/"

    job_url = None
    if img.probable_job_number:
        job_url = f"/ui/jobs/{quote(img.probable_job_number)}/"

    browse_folder_url = None
    if img.folder_id:
        browse_folder_url = f"/ui/browse/folder/{img.folder_id}/"

    ctx = {
        "img": img,
        "links": links,
        "used_in": used_in,
        "related_same_folder": related_same_folder,
        "sibling_job_files": sibling_job_files,
        "settings_obj": settings_obj,
        "open_folder_unc": open_links.get("open_folder_unc"),
        "open_folder_smb": open_links.get("open_folder_smb"),
        "customer_url": customer_url,
        "job_url": job_url,
        "browse_folder_url": browse_folder_url,
    }
    return render(request, "indexer/ui_item.html", ctx)


@login_required
def ui_status(request):
    s = IndexerSettings.load()
    now = timezone.now()

    total_images = Image.objects.count()
    indexed_images = Image.objects.filter(indexed=True).count()
    pending_images = Image.objects.filter(indexed=False, skip_index=False).count()
    skipped_images = Image.objects.filter(skip_index=True).count()

    preview_ready_qs = Image.objects.filter(
        models.Q(preview_status="ok") |
        models.Q(preview_path__isnull=False, preview_path__gt="") |
        models.Q(thumb_path__isnull=False, thumb_path__gt="")
    )
    preview_ready = preview_ready_qs.distinct().count()
    pending_previews = Image.objects.filter(preview_status="pending").count()
    failed_previews = Image.objects.filter(preview_status="failed").count()
    extracted_text_count = Image.objects.exclude(extracted_text__isnull=True).exclude(extracted_text="").count()

    scan_total = ScanDir.objects.count()
    scan_done = ScanDir.objects.filter(done=True).count()
    scan_pending = ScanDir.objects.filter(done=False).count()
    scan_ready = ScanDir.objects.filter(done=False, retry_at__lte=now).count()
    scan_errors = (
        ScanDir.objects.exclude(last_error__isnull=True)
        .exclude(last_error="")
        .count()
    )
    recent_previewed = list(
        preview_ready_qs
        .order_by("-preview_created_at", "-created")
        .only(
            "id",
            "filename",
            "path",
            "preview_path",
            "thumb_path",
            "preview_status",
            "preview_created_at",
            "created",
        )[:5]
    )

    task = (request.GET.get("task") or "").strip()
    logs_qs = TaskLog.objects.all().order_by("-created")
    if task:
        logs_qs = logs_qs.filter(task=task)
    logs = list(logs_qs[:50])

    ctx = {
        "total_images": total_images,
        "indexed_images": indexed_images,
        "pending_images": pending_images,
        "skipped_images": skipped_images,
        "preview_ready": preview_ready,
        "pending_previews": pending_previews,
        "failed_previews": failed_previews,
        "extracted_text_count": extracted_text_count,
        "scan_total": scan_total,
        "scan_done": scan_done,
        "scan_pending": scan_pending,
        "scan_ready": scan_ready,
        "scan_errors": scan_errors,
        "settings_obj": s,
        "logs": logs,
        "task_filter": task,
        "recent_previewed": recent_previewed,
    }
    return render(request, "indexer/ui_status.html", ctx)


@login_required
def ui_similar(request, image_id):
    img = get_object_or_404(Image, id=image_id)

    ctx = {
        "img": img,
    }

    return render(request, "indexer/ui_similar.html", ctx)


@login_required
def ui_retry_preview(request, image_id):
    img = get_object_or_404(Image, id=image_id)
    img.preview_status = "pending"
    img.preview_error = ""
    img.save(update_fields=["preview_status", "preview_error"])
    process_preview_task.delay(str(img.id), force=True)
    return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/ui/health/"))


@login_required
def ui_retry_index(request, image_id):
    img = get_object_or_404(Image, id=image_id)
    img.embedding_status = "pending"
    img.embedding_error = ""
    img.save(update_fields=["embedding_status", "embedding_error"])
    embed_image_task.delay(str(img.id))
    return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/ui/health/"))


@login_required
def ui_requeue_text(request):
    Image.objects.update(
        text_status=ProcessingStatus.PENDING,
        text_error="",
    )
    return HttpResponseRedirect("/ui/")


@login_required
def ui_requeue_metadata(request):
    Image.objects.update(
        metadata_status=ProcessingStatus.PENDING,
        metadata_error="",
    )
    return HttpResponseRedirect("/ui/")


@login_required
def ui_requeue_embedding(request):
    Image.objects.update(
        embedding_status=ProcessingStatus.PENDING,
        embedding_error="",
    )
    return HttpResponseRedirect("/ui/")


@login_required
def ui_health(request):
    qs = Image.objects.filter(indexed=True)

    total = qs.count()

    missing_preview = qs.filter(
        models.Q(preview_path__isnull=True) | models.Q(preview_path="")
    ).count()

    missing_thumb = qs.filter(
        models.Q(thumb_path__isnull=True) | models.Q(thumb_path="")
    ).count()

    missing_text = qs.filter(
        models.Q(extracted_text__isnull=True) | models.Q(extracted_text="")
    ).count()

    summary = get_health_summary()
    recent_errors = get_recent_errors(limit=100)
    top_error_reasons = get_top_error_reasons(limit=20)

    ctx = {
        "total": total,
        "missing_preview": missing_preview,
        "missing_thumb": missing_thumb,
        "missing_text": missing_text,
        "summary": summary,
        "recent_errors": recent_errors,
        "top_error_reasons": top_error_reasons,
    }

    return render(request, "indexer/ui_health.html", ctx)


@login_required
@require_POST
def ui_requeue_stage(request, stage):
    if stage == "preview":
        count = Image.objects.update(
            preview_status=PreviewStatus.PENDING,
            preview_error="",
        )
    elif stage == "text":
        count = Image.objects.exclude(
            text_status=ProcessingStatus.PROCESSING
        ).update(
            text_status=ProcessingStatus.PENDING,
            text_error="",
        )
    elif stage == "metadata":
        count = Image.objects.exclude(
            metadata_status=ProcessingStatus.PROCESSING
        ).update(
            metadata_status=ProcessingStatus.PENDING,
            metadata_error="",
        )
    elif stage == "embedding":
        count = Image.objects.exclude(
            embedding_status=ProcessingStatus.PROCESSING
        ).update(
            embedding_status=ProcessingStatus.PENDING,
            embedding_error="",
        )
    else:
        raise Http404("Unknown stage")

    log("admin", f"Bulk requeue stage={stage} count={count}", "WARNING")

    return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/ui/"))


@login_required
def ui_browse_root(request):
    allowed_root_ids = _allowed_root_ids(request.user)

    folders = (
        Folder.objects.filter(root_id__in=allowed_root_ids, parent__isnull=True)
        .select_related("preview_image", "root")
        .order_by("name")
    )

    return render(
        request,
        "indexer/ui_browse_root.html",
        {
            "folders": folders,
        },
    )


@login_required
def ui_browse_folder(request, folder_id):
    allowed_root_ids = _allowed_root_ids(request.user)

    folder = get_object_or_404(
        Folder.objects.select_related("parent", "root", "preview_image"),
        id=folder_id,
        root_id__in=allowed_root_ids,
    )

    child_folders = _cached_child_folders(folder.id, allowed_root_ids)

    child_folder_ids = [f.id for f in child_folders]
    child_health = _folder_health_counts(child_folder_ids)

    for child in child_folders:
        health = child_health.get(child.id, {})
        child.preview_failed_count = health.get("preview_failed_count", 0)
        child.missing_preview_count = health.get("missing_preview_count", 0)
        child.duplicate_count = health.get("duplicate_count", 0)

    images_qs = (
        Image.objects.filter(folder=folder, root_id__in=allowed_root_ids)
        .select_related("root")
        .order_by("filename")
    )

    paginator = Paginator(images_qs, 60)
    page_obj = paginator.get_page(request.GET.get("page"))

    open_links = _open_folder_links_for_folder(folder)

    duplicate_images = Image.objects.filter(folder=folder).exclude(duplicate_group__isnull=True).exclude(duplicate_group__exact="")
    clustered_images = Image.objects.filter(folder=folder).exclude(visual_cluster_id__isnull=True).exclude(visual_cluster_id__exact="")

    if not request.user.is_superuser:
        duplicate_images = duplicate_images.filter(root_id__in=allowed_root_ids)
        clustered_images = clustered_images.filter(root_id__in=allowed_root_ids)

    duplicate_count = duplicate_images.count()
    clustered_count = clustered_images.count()

    return render(
        request,
        "indexer/ui_browse_folder.html",
        {
            "folder": folder,
            "breadcrumbs": _folder_breadcrumbs(folder),
            "child_folders": child_folders,
            "page_obj": page_obj,
            "open_folder_unc": open_links["open_folder_unc"],
            "open_folder_smb": open_links["open_folder_smb"],
            "search_folder_url": f"/ui/search/?mode=hybrid&folder_id={folder.id}",
            "duplicate_count": duplicate_count,
            "clustered_count": clustered_count,
        },
    )


@login_required
def ui_jobs(request):
    allowed = _allowed_root_ids(request.user)

    q = (request.GET.get("q") or "").strip()

    qs = (
        Image.objects.exclude(probable_job_number="")
        .values("probable_job_number")
        .annotate(
            image_count=Count("id"),
            customer_count=Count("customer_name", distinct=True),
        )
        .order_by("-image_count", "probable_job_number")
    )

    if not request.user.is_superuser and allowed:
        qs = qs.filter(root_id__in=allowed)

    if q:
        qs = qs.filter(probable_job_number__icontains=q)

    page_obj = Paginator(qs, 50).get_page(request.GET.get("page"))

    return render(
        request,
        "indexer/ui_jobs.html",
        {
            "q": q,
            "page_obj": page_obj,
        },
    )


@login_required
def ui_job_detail(request, job_number):
    allowed = _allowed_root_ids(request.user)

    images_qs = (
        Image.objects.select_related("root", "folder")
        .filter(probable_job_number=job_number)
        .order_by("-created", "filename")
    )

    if not request.user.is_superuser and allowed:
        images_qs = images_qs.filter(root_id__in=allowed)

    customer_names = sorted(
        {
            name for name in images_qs.values_list("customer_name", flat=True)
            if name
        }
    )

    folder_paths = sorted(
        {
            rel for rel in images_qs.values_list("relative_dir", flat=True)
            if rel
        }
    )

    page_obj = Paginator(images_qs, 60).get_page(request.GET.get("page"))

    return render(
        request,
        "indexer/ui_job_detail.html",
        {
            "job_number": job_number,
            "customer_names": customer_names,
            "folder_paths": folder_paths[:20],
            "page_obj": page_obj,
            "total_count": images_qs.count(),
        },
    )


@login_required
def ui_customers(request):
    allowed = _allowed_root_ids(request.user)

    q = (request.GET.get("q") or "").strip()

    qs = (
        Image.objects.exclude(customer_name="")
        .values("customer_name")
        .annotate(
            image_count=Count("id"),
            job_count=Count("probable_job_number", distinct=True),
        )
        .order_by("customer_name")
    )

    if not request.user.is_superuser and allowed:
        qs = qs.filter(root_id__in=allowed)

    if q:
        qs = qs.filter(customer_name__icontains=q)

    page_obj = Paginator(qs, 50).get_page(request.GET.get("page"))

    return render(
        request,
        "indexer/ui_customers.html",
        {
            "q": q,
            "page_obj": page_obj,
        },
    )


@login_required
def ui_customer_detail(request, customer_name):
    allowed = _allowed_root_ids(request.user)

    images_qs = (
        Image.objects.select_related("root", "folder")
        .filter(customer_name=customer_name)
        .order_by("-created", "filename")
    )

    if not request.user.is_superuser and allowed:
        images_qs = images_qs.filter(root_id__in=allowed)

    job_numbers = sorted(
        {
            j for j in images_qs.values_list("probable_job_number", flat=True)
            if j
        }
    )

    folder_paths = sorted(
        {
            rel for rel in images_qs.values_list("relative_dir", flat=True)
            if rel
        }
    )

    page_obj = Paginator(images_qs, 60).get_page(request.GET.get("page"))

    return render(
        request,
        "indexer/ui_customer_detail.html",
        {
            "customer_name": customer_name,
            "job_numbers": job_numbers[:30],
            "folder_paths": folder_paths[:20],
            "page_obj": page_obj,
            "total_count": images_qs.count(),
        },
    )


@login_required
def ui_duplicates(request):
    allowed = _allowed_root_ids(request.user)
    q = (request.GET.get("q") or "").strip()

    images_qs = Image.objects.exclude(duplicate_group="")

    if not request.user.is_superuser and allowed:
        images_qs = images_qs.filter(root_id__in=allowed)

    if q:
        images_qs = images_qs.filter(
            Q(duplicate_group__icontains=q)
            | Q(filename__icontains=q)
            | Q(customer_name__icontains=q)
            | Q(probable_job_number__icontains=q)
            | Q(relative_dir__icontains=q)
        )

    group_rows = list(
        images_qs.values("duplicate_group")
        .annotate(
            image_count=Count("id"),
            primary_id=Min("id"),
        )
        .filter(image_count__gt=1)
        .order_by("-image_count", "duplicate_group")
    )

    group_ids = [row["duplicate_group"] for row in group_rows]

    sample_images = {
        img.duplicate_group: img
        for img in (
            Image.objects.select_related("root", "folder")
            .filter(duplicate_group__in=group_ids, id__in=[row["primary_id"] for row in group_rows])
        )
    }

    for row in group_rows:
        row["sample"] = sample_images.get(row["duplicate_group"])

    page_obj = Paginator(group_rows, 50).get_page(request.GET.get("page"))

    return render(
        request,
        "indexer/ui_duplicates.html",
        {
            "q": q,
            "page_obj": page_obj,
        },
    )


@login_required
def ui_duplicate_group(request, group_id):
    allowed = _allowed_root_ids(request.user)

    images_qs = (
        Image.objects.select_related("root", "folder")
        .filter(duplicate_group=group_id)
        .order_by("-is_primary_duplicate", "filename", "path")
    )

    if not request.user.is_superuser and allowed:
        images_qs = images_qs.filter(root_id__in=allowed)

    if not images_qs.exists():
        raise Http404("Duplicate group not found")

    customer_names = sorted(
        {
            name for name in images_qs.values_list("customer_name", flat=True)
            if name
        }
    )

    job_numbers = sorted(
        {
            j for j in images_qs.values_list("probable_job_number", flat=True)
            if j
        }
    )

    folder_paths = sorted(
        {
            rel for rel in images_qs.values_list("relative_dir", flat=True)
            if rel
        }
    )

    page_obj = Paginator(images_qs, 60).get_page(request.GET.get("page"))

    return render(
        request,
        "indexer/ui_duplicate_group.html",
        {
            "group_id": group_id,
            "customer_names": customer_names[:20],
            "job_numbers": job_numbers[:20],
            "folder_paths": folder_paths[:20],
            "page_obj": page_obj,
            "total_count": images_qs.count(),
        },
    )


@login_required
def ui_clusters(request):
    allowed = _allowed_root_ids(request.user)
    q = (request.GET.get("q") or "").strip()

    images_qs = Image.objects.exclude(visual_cluster_id__isnull=True).exclude(visual_cluster_id="")

    if not request.user.is_superuser and allowed:
        images_qs = images_qs.filter(root_id__in=allowed)

    if q:
        images_qs = images_qs.filter(
            Q(visual_cluster_id__icontains=q)
            | Q(filename__icontains=q)
            | Q(customer_name__icontains=q)
            | Q(probable_job_number__icontains=q)
            | Q(relative_dir__icontains=q)
        )

    cluster_rows = list(
        images_qs.values("visual_cluster_id")
        .annotate(
            image_count=Count("id"),
            sample_id=Min("id"),
            max_near_duplicate_count=Max("near_duplicate_count"),
            max_similar_image_count=Max("similar_image_count"),
        )
        .filter(image_count__gt=1)
        .order_by("-image_count", "visual_cluster_id")
    )

    sample_ids = [row["sample_id"] for row in cluster_rows if row["sample_id"]]
    sample_images = {
        img.id: img
        for img in Image.objects.select_related("root", "folder").filter(id__in=sample_ids)
    }

    for row in cluster_rows:
        row["sample"] = sample_images.get(row["sample_id"])

    page_obj = Paginator(cluster_rows, 50).get_page(request.GET.get("page"))

    return render(
        request,
        "indexer/ui_clusters.html",
        {
            "q": q,
            "page_obj": page_obj,
        },
    )


@login_required
def ui_cluster_detail(request, cluster_id):
    allowed = _allowed_root_ids(request.user)

    images_qs = (
        Image.objects.select_related("root", "folder")
        .filter(visual_cluster_id=cluster_id)
        .order_by("-similarity_anchor", "-near_duplicate_count", "filename", "path")
    )

    if not request.user.is_superuser and allowed:
        images_qs = images_qs.filter(root_id__in=allowed)

    if not images_qs.exists():
        raise Http404("Cluster not found")

    customer_names = sorted(
        {name for name in images_qs.values_list("customer_name", flat=True) if name}
    )

    job_numbers = sorted(
        {j for j in images_qs.values_list("probable_job_number", flat=True) if j}
    )

    folder_paths = sorted(
        {rel for rel in images_qs.values_list("relative_dir", flat=True) if rel}
    )

    anchor_ids = set(
        images_qs.filter(similarity_anchor=True).values_list("id", flat=True)
    )

    page_obj = Paginator(images_qs, 60).get_page(request.GET.get("page"))

    return render(
        request,
        "indexer/ui_cluster_detail.html",
        {
            "cluster_id": cluster_id,
            "customer_names": customer_names[:20],
            "job_numbers": job_numbers[:20],
            "folder_paths": folder_paths[:20],
            "anchor_ids": anchor_ids,
            "page_obj": page_obj,
            "total_count": images_qs.count(),
        },
    )


@login_required
def ui_folder_health(request):
    allowed = _allowed_root_ids(request.user)

    only_issues = (request.GET.get("only_issues") or "").strip() in {"1", "true", "yes"}
    q = (request.GET.get("q") or "").strip()

    folders = Folder.objects.select_related("root")

    if not request.user.is_superuser and allowed:
        folders = folders.filter(root_id__in=allowed)

    if q:
        folders = folders.filter(
            Q(name__icontains=q) | Q(rel_path__icontains=q)
        )

    folders = folders.annotate(
        calc_image_total=Count("images", distinct=True),

        calc_preview_missing_count=Count(
            "images",
            filter=Q(images__preview_status=PreviewStatus.PENDING),
            distinct=True,
        ),
        calc_preview_failed_count=Count(
            "images",
            filter=Q(images__preview_status=PreviewStatus.FAILED),
            distinct=True,
        ),

        calc_metadata_missing_count=Count(
            "images",
            filter=Q(images__metadata_status=ProcessingStatus.PENDING),
            distinct=True,
        ),
        calc_metadata_failed_count=Count(
            "images",
            filter=Q(images__metadata_status=ProcessingStatus.FAILED),
            distinct=True,
        ),

        calc_duplicate_count=Count(
            "images",
            filter=Q(images__duplicate_group__isnull=False) & ~Q(images__duplicate_group=""),
            distinct=True,
        ),
        calc_clustered_count=Count(
            "images",
            filter=Q(images__visual_cluster_id__isnull=False) & ~Q(images__visual_cluster_id=""),
            distinct=True,
        ),
    ).annotate(
        health_score=(
            Case(
                When(calc_preview_failed_count__gt=0, then=3),
                default=0,
                output_field=IntegerField(),
            )
            + Case(
                When(calc_metadata_failed_count__gt=0, then=3),
                default=0,
                output_field=IntegerField(),
            )
            + Case(
                When(calc_preview_missing_count__gt=0, then=2),
                default=0,
                output_field=IntegerField(),
            )
            + Case(
                When(calc_metadata_missing_count__gt=0, then=2),
                default=0,
                output_field=IntegerField(),
            )
            + Case(
                When(calc_duplicate_count__gt=0, then=1),
                default=0,
                output_field=IntegerField(),
            )
        )
    )

    if only_issues:
        folders = folders.filter(
            Q(calc_preview_missing_count__gt=0)
            | Q(calc_preview_failed_count__gt=0)
            | Q(calc_metadata_missing_count__gt=0)
            | Q(calc_metadata_failed_count__gt=0)
            | Q(calc_duplicate_count__gt=0)
            | Q(calc_clustered_count__gt=0)
        )

    folders = folders.order_by(
        "-health_score",
        "-calc_preview_failed_count",
        "-calc_metadata_failed_count",
        "-calc_preview_missing_count",
        "-calc_metadata_missing_count",
        "-calc_duplicate_count",
        "-calc_clustered_count",
        "rel_path",
    )

    summary = folders.aggregate(
        folder_count=Count("id"),
        total_images=Count("images", distinct=True),
        total_preview_missing=Count(
            "images",
            filter=Q(images__preview_status=PreviewStatus.PENDING),
            distinct=True,
        ),
        total_preview_failed=Count(
            "images",
            filter=Q(images__preview_status=PreviewStatus.FAILED),
            distinct=True,
        ),
        total_metadata_missing=Count(
            "images",
            filter=Q(images__metadata_status=ProcessingStatus.PENDING),
            distinct=True,
        ),
        total_metadata_failed=Count(
            "images",
            filter=Q(images__metadata_status=ProcessingStatus.FAILED),
            distinct=True,
        ),
        total_duplicates=Count(
            "images",
            filter=Q(images__duplicate_group__isnull=False) & ~Q(images__duplicate_group=""),
            distinct=True,
        ),
        total_clusters=Count(
            "images",
            filter=Q(images__visual_cluster_id__isnull=False) & ~Q(images__visual_cluster_id=""),
            distinct=True,
        ),
    )

    page_obj = Paginator(folders, 100).get_page(request.GET.get("page"))

    return render(
        request,
        "indexer/ui_folder_health.html",
        {
            "page_obj": page_obj,
            "summary": summary,
            "q": q,
            "only_issues": only_issues,
        },
    )


@login_required
def ui_folder_issue_detail(request, folder_id, issue):
    allowed = _allowed_root_ids(request.user)

    folder = get_object_or_404(
        Folder.objects.select_related("root"),
        id=folder_id,
    )

    if not request.user.is_superuser and allowed and folder.root_id not in allowed:
        return render(request, "indexer/ui_not_allowed.html", status=404)

    prefix = (folder.rel_path or "").strip("/")

    qs = Image.objects.select_related("root", "folder").filter(root_id=folder.root_id)

    if prefix:
        qs = qs.filter(
            Q(relative_dir=prefix) |
            Q(relative_dir__startswith=prefix + "/")
        )

    issue_label = issue

    if issue == "preview_missing":
        qs = qs.filter(preview_status=PreviewStatus.PENDING)
        issue_label = "Preview Missing"
    elif issue == "preview_failed":
        qs = qs.filter(preview_status=PreviewStatus.FAILED)
        issue_label = "Preview Failed"
    elif issue == "metadata_missing":
        qs = qs.filter(metadata_status=ProcessingStatus.PENDING)
        issue_label = "Metadata Missing"
    elif issue == "metadata_failed":
        qs = qs.filter(metadata_status=ProcessingStatus.FAILED)
        issue_label = "Metadata Failed"
    elif issue == "duplicates":
        qs = qs.exclude(duplicate_group__isnull=True).exclude(duplicate_group="")
        issue_label = "Duplicates"
    elif issue == "clusters":
        qs = qs.exclude(visual_cluster_id__isnull=True).exclude(visual_cluster_id="")
        issue_label = "Clusters"
    else:
        raise Http404("Unknown folder issue type")

    results = list(qs.order_by("filename")[:500])

    ctx = {
        "folder": folder,
        "issue": issue,
        "issue_label": issue_label,
        "results": results,
        "result_count": len(results),
    }

    if request.headers.get("HX-Request") == "true":
        return render(
            request,
            "indexer/partials/folder_issue_results.html",
            ctx,
        )

    return render(
        request,
        "indexer/ui_folder_issue_detail.html",
        ctx,
    )


@require_POST
def ui_requeue_stage_bulk(request, stage):
    qs = Image.objects.all()

    if stage == "preview":
        updated = qs.exclude(preview_status=PreviewStatus.PENDING).update(
            preview_status=PreviewStatus.PENDING,
            preview_error="",
        )
        messages.success(request, f"Requeued preview for {updated} items.")
    elif stage == "text":
        updated = qs.exclude(text_status=ProcessingStatus.PENDING).update(
            text_status=ProcessingStatus.PENDING,
            text_error="",
        )
        messages.success(request, f"Requeued text extraction for {updated} items.")
    elif stage == "metadata":
        updated = qs.exclude(metadata_status=ProcessingStatus.PENDING).update(
            metadata_status=ProcessingStatus.PENDING,
            metadata_error="",
        )
        messages.success(request, f"Requeued metadata for {updated} items.")
    elif stage == "embedding":
        updated = qs.exclude(embedding_status=ProcessingStatus.PENDING).update(
            embedding_status=ProcessingStatus.PENDING,
            embedding_error="",
        )
        messages.success(request, f"Requeued embeddings for {updated} items.")
    else:
        messages.error(request, f"Unknown stage: {stage}")



def landing(request):
    if request.user.is_authenticated:
        return redirect("ui_home")
    return render(request, "indexer/landing.html")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("ui_home")

    next_url = request.GET.get("next") or request.POST.get("next") or "/ui/"

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        remember_me = request.POST.get("remember_me") == "on"

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)

            if remember_me:
                request.session.set_expiry(60 * 60 * 24 * 30)
            else:
                request.session.set_expiry(0)

            return redirect(next_url)

        messages.error(request, "Invalid username or password.")

    return render(
        request,
        "indexer/login.html",
        {
            "next": next_url,
        },
    )


def logout_view(request):
    logout(request)
    return redirect("landing")