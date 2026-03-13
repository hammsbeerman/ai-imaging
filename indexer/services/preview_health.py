import os

from indexer.models import Image, PreviewStatus
from indexer.previews import abs_preview_path


def get_preview_drift(limit=100):
    missing = []

    qs = (
        Image.objects
        .filter(preview_status=PreviewStatus.OK)
        .exclude(preview_path="")
        .exclude(preview_path=None)
        .only("id", "preview_path", "filename")
    )

    for img in qs.iterator():
        p = abs_preview_path(img.preview_path)

        if not p or not os.path.exists(p):
            missing.append(img)

        if len(missing) >= limit:
            break

    return missing

def get_preview_drift_count():
    count = 0

    qs = (
        Image.objects
        .filter(preview_status=PreviewStatus.OK)
        .exclude(preview_path="")
        .exclude(preview_path=None)
        .only("preview_path")
    )

    for img in qs.iterator():
        p = abs_preview_path(img.preview_path)

        if not p or not os.path.exists(p):
            count += 1

    return count