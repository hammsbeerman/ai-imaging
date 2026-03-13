import os

from indexer.previews import abs_preview_path


def preview_files_exist(img) -> bool:
    thumb_path = abs_preview_path(getattr(img, "thumb_path", ""))
    preview_path = abs_preview_path(getattr(img, "preview_path", ""))

    if thumb_path and os.path.exists(thumb_path):
        return True
    if preview_path and os.path.exists(preview_path):
        return True
    return False