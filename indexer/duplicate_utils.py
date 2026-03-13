import hashlib

import imagehash
from PIL import Image as PILImage


def file_sha256(path, chunk_size=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_phash(path):
    with PILImage.open(path) as img:
        return str(imagehash.phash(img))