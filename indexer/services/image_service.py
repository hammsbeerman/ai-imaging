from indexer.models import Image
from indexer.services.permission_service import filter_images_for_user


def build_image_summary(img, score=None):
    return {
        "id": str(img.id),
        "filename": img.filename,
        "path": img.path,
        "file_ext": getattr(img, "file_ext", "") or "",
        "thumb_url": f"/api/thumb/{img.id}",
        "preview_url": f"/api/thumb/{img.id}",
        "score": score,
        "indexed": bool(getattr(img, "indexed", False)),
        "preview_status": getattr(img, "preview_status", ""),
        "text_status": getattr(img, "text_status", ""),
        "embedding_status": getattr(img, "embedding_status", ""),
        "customer_name": getattr(img, "customer_name", "") or "",
        "job_type": getattr(img, "job_type", "") or "",
    }


def _same_folder_qs(img):
    folder = img.path.rsplit("/", 1)[0] if "/" in img.path else ""
    if not folder:
        return Image.objects.none()

    return Image.objects.filter(path__startswith=folder + "/").exclude(id=img.id)


def _same_stem_qs(img):
    stem = img.filename.rsplit(".", 1)[0].strip()
    if not stem:
        return Image.objects.none()

    return Image.objects.filter(filename__istartswith=stem).exclude(id=img.id)


def build_image_detail(user, img):
    same_folder = filter_images_for_user(
        _same_folder_qs(img).order_by("filename")[:12],
        user,
    )
    sibling_job_files = filter_images_for_user(
        _same_stem_qs(img).order_by("filename")[:12],
        user,
    )

    return {
        "id": str(img.id),
        "filename": img.filename,
        "path": img.path,
        "file_ext": getattr(img, "file_ext", "") or "",
        "preview_status": getattr(img, "preview_status", ""),
        "preview_error": getattr(img, "preview_error", "") or "",
        "text_status": getattr(img, "text_status", ""),
        "text_error": getattr(img, "text_error", "") or "",
        "embedding_status": getattr(img, "embedding_status", ""),
        "embedding_error": getattr(img, "embedding_error", "") or "",
        "metadata_status": getattr(img, "metadata_status", ""),
        "metadata_error": getattr(img, "metadata_error", "") or "",
        "preview_url": f"/api/thumb/{img.id}",
        "thumb_url": f"/api/thumb/{img.id}",
        "extracted_text": getattr(img, "extracted_text", "") or "",
        "folder_tokens": getattr(img, "folder_tokens", "") or "",
        "customer_name": getattr(img, "customer_name", "") or "",
        "job_type": getattr(img, "job_type", "") or "",
        "sibling_job_files": [build_image_summary(x) for x in sibling_job_files],
        "related_same_folder": [build_image_summary(x) for x in same_folder],
        "linked_assets": [],
        "used_in": [],
    }