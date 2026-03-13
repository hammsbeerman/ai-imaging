import os
from pathlib import Path
from datetime import datetime, timedelta, timezone as dt_timezone

from celery import shared_task
from django.db import close_old_connections
from django.utils import timezone

from indexer.folders import attach_image_to_folder
from indexer.metadata_utils import (
    relative_dir as compute_relative_dir,
    folder_depth as compute_folder_depth,
)
from indexer.models import (
    Image,
    IndexerSettings,
    AccessRoot,
    ScanDir,
    AssetLink,
    PreviewStatus,
)
from indexer.index_images import run_index
from indexer.text_extract import extract_pdf_text
from indexer.tasklog import log, trim
from indexer.locks import acquire_lock, release_lock, refresh_lock
from indexer.indd_links import collect_indd_relationships
from indexer.tasks_preview import process_preview_task as active_process_preview_task
from indexer.scanner import should_index_file, should_scan_dir

"""
LEGACY TASKS MODULE

This file contains older monolithic / compatibility task entrypoints.

Keep:
- scan_task
- index_task
- enrich_task
- compatibility wrappers for preview-related tasks still referenced elsewhere

Do not let this file own preview generation logic.
The active preview pipeline lives in:
- indexer.tasks_preview
"""


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/").rstrip("/")


def _pick_root(full_path: str, roots: list[AccessRoot]) -> AccessRoot | None:
    fp = _norm(full_path)
    best = None
    best_len = -1
    for r in roots:
        rp = _norm(r.scan_path_root)
        if not rp:
            continue
        prefix = rp + "/"
        if fp.startswith(prefix) and len(prefix) > best_len:
            best = r
            best_len = len(prefix)
    return best


def _get_image_path(img: Image) -> str:
    return img.path


def _link_existing_image(path: str):
    return Image.objects.filter(path=path).first()


@shared_task
def scan_task():
    close_old_connections()

    s = IndexerSettings.load()
    if not s.enabled:
        log("scan", "disabled (IndexerSettings.enabled = False)", "WARN")
        return {"status": "disabled"}

    roots = list(AccessRoot.objects.all())

    root_prefixes = []
    for r in roots:
        pref = (r.scan_path_root or "").rstrip("/").replace("\\", "/") + "/"
        root_prefixes.append((pref, r))

    def pick_root_fast(full_path: str):
        fp = full_path.replace("\\", "/")
        best = None
        best_len = -1
        for pref, r in root_prefixes:
            if pref and fp.startswith(pref) and len(pref) > best_len:
                best = r
                best_len = len(pref)
        return best

    batch = list(
        ScanDir.objects
        .filter(done=False, retry_at__lte=timezone.now())
        .order_by("retry_at", "updated")[:50]
    )

    if not batch:
        log("scan", "idle (no ScanDir ready)")
        trim()
        return {"status": "idle"}

    dirs_scanned = 0
    dirs_enqueued = 0
    dirs_skipped = 0
    errors = 0

    files_seen = 0
    files_indexable = 0
    images_existing = 0
    images_created = 0

    log("scan", f"starting dirs={len(batch)} base_scan_path={s.scan_path}")

    for row in batch:
        path = row.path
        dirs_scanned += 1

        try:
            child_dirs = []
            candidates = []

            with os.scandir(path) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if should_scan_dir(entry.name):
                                child_dirs.append(entry.path)
                            else:
                                dirs_skipped += 1
                            continue
                    except Exception:
                        continue

                    try:
                        if not entry.is_file(follow_symlinks=False):
                            continue
                    except Exception:
                        continue

                    files_seen += 1

                    name = entry.name
                    if not should_index_file(name):
                        continue

                    files_indexable += 1
                    full = entry.path

                    try:
                        st = entry.stat(follow_symlinks=False)
                        size = st.st_size
                        mtime = datetime.fromtimestamp(st.st_mtime, tz=dt_timezone.utc)
                    except Exception:
                        size = None
                        mtime = None

                    ext = os.path.splitext(name)[1].lower()
                    root_obj = pick_root_fast(full)
                    root_id = root_obj.id if root_obj else None

                    root_base = (
                        root_obj.scan_path_root
                        if root_obj and root_obj.scan_path_root
                        else s.scan_path
                    )

                    rel_dir = compute_relative_dir(full, root=root_base)
                    if rel_dir in (".",):
                        rel_dir = ""

                    depth = compute_folder_depth(full, root=root_base)

                    candidates.append(
                        (full, name, size, mtime, ext, root_id, rel_dir, depth)
                    )

            if child_dirs:
                existing_dirs = set(
                    ScanDir.objects.filter(path__in=child_dirs).values_list("path", flat=True)
                )
                to_create_dirs = [ScanDir(path=p) for p in child_dirs if p not in existing_dirs]
                if to_create_dirs:
                    ScanDir.objects.bulk_create(
                        to_create_dirs,
                        ignore_conflicts=True,
                        batch_size=1000,
                    )
                    dirs_enqueued += len(to_create_dirs)

            if candidates:
                paths = [c[0] for c in candidates]
                existing_paths = set(
                    Image.objects.filter(path__in=paths).values_list("path", flat=True)
                )
                images_existing += len(existing_paths)

                to_create_imgs = []
                for (full, name, size, mtime, ext, root_id, rel_dir, depth) in candidates:
                    if full in existing_paths:
                        continue
                    to_create_imgs.append(
                        Image(
                            path=full,
                            filename=name,
                            size=size,
                            ext=ext,
                            file_ext=ext,
                            mtime=mtime,
                            root_id=root_id,
                            relative_dir=rel_dir,
                            folder_depth=depth,
                        )
                    )

                if to_create_imgs:
                    Image.objects.bulk_create(
                        to_create_imgs,
                        ignore_conflicts=True,
                        batch_size=1000,
                    )
                    images_created += len(to_create_imgs)

                candidate_map = {
                    full: {
                        "filename": name,
                        "size": size,
                        "mtime": mtime,
                        "ext": ext,
                        "file_ext": ext,
                        "root_id": root_id,
                        "relative_dir": rel_dir,
                        "folder_depth": depth,
                    }
                    for (full, name, size, mtime, ext, root_id, rel_dir, depth) in candidates
                }

                images = list(
                    Image.objects.filter(path__in=paths).select_related("root", "folder")
                )

                for img in images:
                    meta = candidate_map.get(img.path)
                    if not meta:
                        continue

                    update_fields = []

                    if img.filename != meta["filename"]:
                        img.filename = meta["filename"]
                        update_fields.append("filename")

                    if img.size != meta["size"]:
                        img.size = meta["size"]
                        update_fields.append("size")

                    if img.mtime != meta["mtime"]:
                        img.mtime = meta["mtime"]
                        update_fields.append("mtime")

                    if img.ext != meta["ext"]:
                        img.ext = meta["ext"]
                        update_fields.append("ext")

                    if img.file_ext != meta["file_ext"]:
                        img.file_ext = meta["file_ext"]
                        update_fields.append("file_ext")

                    if img.root_id != meta["root_id"]:
                        img.root_id = meta["root_id"]
                        update_fields.append("root")

                    if img.relative_dir != meta["relative_dir"]:
                        img.relative_dir = meta["relative_dir"]
                        update_fields.append("relative_dir")

                    if img.folder_depth != meta["folder_depth"]:
                        img.folder_depth = meta["folder_depth"]
                        update_fields.append("folder_depth")

                    if update_fields:
                        img.save(update_fields=update_fields)

                    attach_image_to_folder(img)

            row.done = True
            row.last_error = None
            row.save(update_fields=["done", "last_error"])

        except Exception as e:
            errors += 1
            row.attempts = int(row.attempts or 0) + 1
            delay_min = min(60, 2 ** min(row.attempts, 6))
            row.retry_at = timezone.now() + timedelta(minutes=delay_min)
            row.last_error = str(e)
            row.save(update_fields=["attempts", "retry_at", "last_error"])
            log("scan", f"ERROR dir={path}: {e} (retry in {delay_min}m)", "ERROR")

    log(
        "scan",
        "finished "
        f"dirs_scanned={dirs_scanned} dirs_enqueued={dirs_enqueued} dirs_skipped={dirs_skipped} "
        f"files_seen={files_seen} files_indexable={files_indexable} "
        f"images_created={images_created} images_existing={images_existing} "
        f"errors={errors}"
    )
    trim()

    return {
        "dirs_scanned": dirs_scanned,
        "dirs_enqueued": dirs_enqueued,
        "dirs_skipped": dirs_skipped,
        "files_seen": files_seen,
        "files_indexable": files_indexable,
        "images_created": images_created,
        "images_existing": images_existing,
        "errors": errors,
    }


@shared_task
def index_task():
    close_old_connections()

    settings_obj = IndexerSettings.load()
    if not settings_obj.enabled:
        log("index", "disabled (IndexerSettings.enabled = False)", "WARN")
        trim()
        return {"status": "disabled"}

    pending_total = Image.objects.filter(indexed=False).count()
    log("index", f"pending_images={pending_total}")

    if pending_total == 0:
        log("index", "idle (no pending images)")
        trim()
        return {"status": "idle"}

    lock_key = "lock:index_task"
    token = acquire_lock(lock_key, ttl=900)
    if not token:
        log("index", "skipped (lock held)")
        trim()
        return {"status": "skipped"}

    batch_size = int(settings_obj.index_batch_size or 50)
    images = list(Image.objects.filter(indexed=False).order_by("created")[:batch_size])
    selected = len(images)

    log("index", f"starting batch_size={batch_size} selected={selected}")

    try:
        refresh_lock(lock_key, token, ttl=900)

        run_index(batch_size=batch_size, image_ids=[i.id for i in images])

        refresh_lock(lock_key, token, ttl=900)

        done_now = Image.objects.filter(id__in=[i.id for i in images], indexed=True).count()
        still_pending = Image.objects.filter(indexed=False).count()
        log("index", f"finished done_now={done_now}/{selected} pending_remaining={still_pending}")
        return {
            "batch_size": batch_size,
            "selected": selected,
            "done_now": done_now,
            "pending_remaining": still_pending,
        }

    except Exception as e:
        log("index", f"FAILED: {e}", "ERROR")
        raise

    finally:
        release_lock(lock_key, token)
        trim()


@shared_task
def enrich_task():
    close_old_connections()

    settings_obj = IndexerSettings.load()
    if not settings_obj.enabled:
        log("enrich", "disabled (IndexerSettings.enabled = False)", "WARN")
        return {"status": "disabled"}

    batch_size = int(settings_obj.enrich_batch_size or 200)

    log("enrich", f"starting batch_size={batch_size}")

    meta_qs = (
        Image.objects.filter(size__isnull=True)
        | Image.objects.filter(mtime__isnull=True)
        | Image.objects.filter(ext__isnull=True)
    )
    pdf_qs = Image.objects.filter(ext=".pdf", text__isnull=True)

    meta_batch = list(meta_qs[:batch_size])
    pdf_batch = list(pdf_qs[:batch_size])

    touched = 0

    for img in meta_batch:
        try:
            st = os.stat(img.path)
            img.size = st.st_size
            img.mtime = timezone.datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
        except Exception:
            pass

        if not img.ext:
            img.ext = os.path.splitext(img.filename or img.path)[1].lower()

        img.save(update_fields=["size", "mtime", "ext"])
        touched += 1

    for img in pdf_batch:
        img.text = extract_pdf_text(img.path)
        img.save(update_fields=["text"])
        touched += 1

    log("enrich", f"finished touched={touched}")
    trim()
    return {"touched": touched}


@shared_task
def process_preview_task(image_id):
    """
    Backward-compatible wrapper.
    All real preview work lives in indexer.tasks_preview.process_preview_task.
    """
    close_old_connections()
    return active_process_preview_task(image_id)


@shared_task
def retry_preview_task(image_id):
    close_old_connections()
    return active_process_preview_task(image_id)


@shared_task
def queue_missing_previews_task(batch_size=200):
    """
    Compatibility task that queues preview processing through the active preview task.
    """
    close_old_connections()

    qs = (
        Image.objects
        .filter(preview_status__in=[PreviewStatus.PENDING, PreviewStatus.FAILED])
        .order_by("created")[:batch_size]
    )

    queued = 0
    for img in qs:
        active_process_preview_task.delay(str(img.pk))
        queued += 1

    return {"queued": queued}


@shared_task
def sync_indd_links_task(image_id):
    close_old_connections()

    img = Image.objects.get(pk=image_id)
    source_path = _get_image_path(img)
    ext = Path(source_path).suffix.lower()

    if ext != ".indd":
        return {"ok": False, "reason": "not indd"}

    rel = collect_indd_relationships(source_path)

    AssetLink.objects.filter(parent=img).delete()

    links = rel.get("links", [])
    for item in links:
        linked_path = item.get("resolved_path") or item.get("raw_path") or ""
        linked_image = _link_existing_image(linked_path) if linked_path and os.path.exists(linked_path) else None

        AssetLink.objects.create(
            parent=img,
            linked_image=linked_image,
            linked_path=linked_path,
            raw_path=item.get("raw_path", ""),
            source=item.get("source", ""),
            exists=item.get("exists", False),
            missing=not item.get("exists", False),
            xml_file=item.get("xml_file") or "",
        )

    sibling_pdf = rel.get("sibling_pdf")
    if sibling_pdf:
        sibling_exists = os.path.exists(sibling_pdf)
        AssetLink.objects.create(
            parent=img,
            linked_image=_link_existing_image(sibling_pdf) if sibling_exists else None,
            linked_path=sibling_pdf,
            raw_path=sibling_pdf,
            source="sibling_pdf",
            exists=sibling_exists,
            missing=not sibling_exists,
            xml_file="",
        )

    return {
        "ok": True,
        "count": AssetLink.objects.filter(parent=img).count(),
    }


@shared_task
def rebuild_indd_links_task(batch_size=100):
    close_old_connections()

    qs = Image.objects.filter(file_ext=".indd").order_by("created")[:batch_size]
    count = 0
    for img in qs:
        sync_indd_links_task.delay(str(img.pk))
        count += 1
    return {"queued": count}


@shared_task
def retry_index_task(image_id):
    close_old_connections()

    try:
        img = Image.objects.get(id=image_id)
    except Image.DoesNotExist:
        return {"error": "image not found"}

    preview_result = active_process_preview_task(image_id)

    img.indexed = False
    img.save(update_fields=["indexed"])

    index_result = run_index(batch_size=1, image_ids=[img.id])

    return {
        "ok": True,
        "preview_result": preview_result,
        "index_result": index_result,
        "image_id": str(img.id),
    }