import os

from indexer.models import Image, IndexerSettings, PreviewStatus
from indexer.clip_embedder import embed_image
from indexer.qdrant import client, COLLECTION, ensure_collection
from indexer.tasklog import log
from indexer.text_extract import extract_searchable_text
from indexer.previews import generate_preview, abs_preview_path


def _preview_status_for_error(error: str) -> str:
    error = (error or "").strip()

    unsupported_markers = [
        "INDD preview unsupported:",
        "Unsupported extension:",
        "Skipped font helper SVG",
    ]

    if any(error.startswith(marker) for marker in unsupported_markers):
        return PreviewStatus.UNSUPPORTED

    return PreviewStatus.FAILED


def _get_or_build_preview(img: Image, force: bool = False) -> str | None:
    preview_abs = abs_preview_path(img.preview_path)
    if not force and preview_abs and os.path.exists(preview_abs):
        return preview_abs

    result = generate_preview(img.path)

    img.file_ext = img.file_ext or (img.ext or "")
    img.extracted_text = extract_searchable_text(img.path)

    if result.ok:
        img.preview_path = result.preview_path or ""
        img.thumb_path = result.thumb_path or ""
        img.preview_status = PreviewStatus.OK
        img.preview_error = ""
        img.preview_source = result.preview_source or ""
        img.width = result.width
        img.height = result.height
    else:
        error = (result.error or "").strip()
        img.preview_status = _preview_status_for_error(error)
        img.preview_error = error or "unknown preview error"

    img.save(update_fields=[
        "file_ext",
        "preview_path",
        "thumb_path",
        "preview_status",
        "preview_error",
        "preview_source",
        "width",
        "height",
        "extracted_text",
    ])

    preview_abs = abs_preview_path(img.preview_path)
    return preview_abs if preview_abs and os.path.exists(preview_abs) else None


def _embedding_source_for_index(img: Image) -> str | None:
    preview_abs = abs_preview_path(img.preview_path)
    thumb_abs = abs_preview_path(img.thumb_path)

    if preview_abs and os.path.exists(preview_abs):
        return preview_abs

    if thumb_abs and os.path.exists(thumb_abs):
        return thumb_abs

    if os.path.exists(img.path):
        return img.path

    return None


def run_index(batch_size: int = 100, image_ids=None):
    settings_obj = IndexerSettings.load()
    if not settings_obj.enabled:
        return

    ensure_collection()

    qs = Image.objects.filter(indexed=False, skip_index=False).order_by("created")
    if image_ids:
        qs = qs.filter(id__in=image_ids).order_by("created")

    images = list(qs[:batch_size])

    processed = ok = failed = 0

    for img in images:
        processed += 1
        try:
            _get_or_build_preview(img)

            source_path = _embedding_source_for_index(img)
            if not source_path:
                failed += 1
                log("index", f"no embedding source for {img.path}", "WARN")
                continue

            vector = embed_image(source_path)

            client.upsert(
                collection_name=COLLECTION,
                points=[{
                    "id": str(img.id),
                    "vector": vector,
                    "payload": {
                        "path": img.path,
                        "filename": img.filename,
                        "root_id": img.root_id,
                        "relative_dir": getattr(img, "relative_dir", "") or "",
                        "probable_job_number": getattr(img, "probable_job_number", "") or "",
                        "customer_name": getattr(img, "customer_name", "") or "",
                        "job_type": getattr(img, "job_type", "") or "",
                    },
                }],
            )

            img.indexed = True
            img.save(update_fields=["indexed"])
            ok += 1

            if processed % 10 == 0:
                log("index", f"progress processed={processed} ok={ok} failed={failed}")

        except Exception as e:
            failed += 1
            log("index", f"Failed path={img.path}: {e}", "ERROR")

    log("index", f"batch done processed={processed} ok={ok} failed={failed}")
    return {"processed": processed, "ok": ok, "failed": failed}