import hashlib
import os

from django.conf import settings


from indexer.previewers import build_preview_for_file


def preview_root() -> str:
    base = str(getattr(settings, "INDEX_PREVIEW_ROOT", "") or "").strip()
    if not base:
        raise RuntimeError("INDEX_PREVIEW_ROOT is not configured")

    return os.path.abspath(base)


def preview_mount_check_path() -> str:
    path = str(getattr(settings, "INDEX_PREVIEW_MOUNT_CHECK", "") or "").strip()
    if path:
        return os.path.abspath(path)

    # fall back to preview_root only if no dedicated mount-check path is configured
    return preview_root()


def ensure_preview_root_ready() -> str:
    base = preview_root()
    mount_check = preview_mount_check_path()

    if not os.path.exists(mount_check):
        raise RuntimeError(f"Preview mount check path does not exist: {mount_check}")

    if not os.access(mount_check, os.R_OK | os.W_OK):
        raise RuntimeError(f"Preview mount check path is not readable/writable: {mount_check}")

    os.makedirs(base, exist_ok=True)
    if not os.access(base, os.R_OK | os.W_OK):
        raise RuntimeError(f"Preview root is not readable/writable: {base}")

    return base


def _preview_relpaths_for(source_path: str) -> tuple[str, str]:
    key = hashlib.sha1(os.path.abspath(source_path).encode("utf-8")).hexdigest()
    a = key[:2]
    b = key[2:4]
    preview_rel = f"previews/{a}/{b}/{key}.jpg"
    thumb_rel = f"thumbs/{a}/{b}/{key}.jpg"
    return preview_rel, thumb_rel


def abs_preview_path(rel_path: str | None) -> str | None:
    if not rel_path:
        return None

    rel = str(rel_path).strip().replace("\\", "/")
    if not rel:
        return None

    if os.path.isabs(rel):
        return rel

    return os.path.join(preview_root(), rel)


def generate_preview(path: str):
    base = ensure_preview_root_ready()

    preview_rel, thumb_rel = _preview_relpaths_for(path)
    preview_abs = os.path.join(base, preview_rel)
    thumb_abs = os.path.join(base, thumb_rel)

    preview_dir = os.path.dirname(preview_abs)
    thumb_dir = os.path.dirname(thumb_abs)

    os.makedirs(preview_dir, exist_ok=True)
    os.makedirs(thumb_dir, exist_ok=True)

    result = build_preview_for_file(path, preview_dir, thumb_dir)

    if result.ok:
        result.preview_path = preview_rel
        result.thumb_path = thumb_rel

    return result
