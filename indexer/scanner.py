import os
import time
from pathlib import Path
from datetime import datetime, timezone as dt_timezone

from indexer.previewers import PREVIEWABLE_EXTENSIONS
from .models import Image, AccessRoot, IndexerSettings


SKIP_FILENAMES = {".ds_store", "thumbs.db", "desktop.ini"}
SKIP_PREFIXES = ("._",)

SKIP_DIR_NAMES = {
    "__pycache__",
    ".git",
    ".svn",
    ".hg",
    ".idea",
    ".vscode",
    "node_modules",
    "$recycle.bin",
    "system volume information",

    # Adobe / photo app junk
    "cache",
    "caches",
    "lrdata",
    "preview cache",
    "previews",
    "smart previews",
    "smart previews.lrdata",
    "thumbnails",
    "thumbs",
    "temp",
    "tmp",    
    "@eadir", 
    ".spotlight-v100", ".trashes", ".fseventsd",
}

SKIP_DIR_NAME_CONTAINS = {
    ".lrdata",
    "lightroom catalog previews",
    "lightroom catalog smart previews",
    "camera raw cache",
    "thumbnail cache",
    "sync temp",
    "autosave",
    "backup cache",
}

INDEXABLE_EXTENSIONS = {
    ".jpg",".jpeg",".png",".tif",".tiff",".bmp",".gif",".webp",
    ".dng",".cr2",".nef",".arw",".raf",
    ".psd",".ai",".eps",".svg",
    ".pdf",".indd"
}

LOG_EVERY_SECONDS = 10
MAX_FILES_PER_RUN = 100
SKIP_HIDDEN_DIRS = True


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/").rstrip("/")


def is_supported_file(path: str) -> bool:
    return Path(path).suffix.lower() in INDEXABLE_EXTENSIONS


def should_index_file(filename: str) -> bool:
    base = os.path.basename(filename or "")
    lf = base.lower()

    if lf in SKIP_FILENAMES:
        return False
    if lf.startswith(SKIP_PREFIXES):
        return False

    return is_supported_file(lf)


def should_scan_dir(dirname: str) -> bool:
    if not dirname:
        return False

    d = dirname.strip()
    dl = d.lower()

    if SKIP_HIDDEN_DIRS and d.startswith("."):
        return False

    if dl in SKIP_DIR_NAMES:
        return False

    for frag in SKIP_DIR_NAME_CONTAINS:
        if frag in dl:
            return False

    return True


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


def scan_directory(root: str | None = None) -> int:
    settings = IndexerSettings.load()
    if not settings.enabled:
        return 0

    root = _norm(root or settings.scan_path)
    roots = list(AccessRoot.objects.all())

    created = 0
    seen_files = 0
    indexable_seen = 0
    skipped_files = 0
    skipped_dirs = 0
    last_log = time.time()

    def _onerror(_err):
        nonlocal skipped_dirs
        skipped_dirs += 1

    for dirpath, dirnames, filenames in os.walk(root, onerror=_onerror, followlinks=False):
        before = len(dirnames)
        dirnames[:] = [d for d in dirnames if should_scan_dir(d)]
        skipped_dirs += max(0, before - len(dirnames))

        try:
            _ = os.listdir(dirpath)
        except Exception:
            skipped_dirs += 1
            dirnames[:] = []
            continue

        for f in filenames:
            if MAX_FILES_PER_RUN is not None and seen_files >= MAX_FILES_PER_RUN:
                print(f"[scan] max files reached ({MAX_FILES_PER_RUN}); stopping this run")
                return created

            seen_files += 1

            if not should_index_file(f):
                skipped_files += 1
                continue

            indexable_seen += 1
            full = os.path.join(dirpath, f)

            try:
                st = os.stat(full)
                size = st.st_size
                mtime = datetime.fromtimestamp(st.st_mtime, tz=dt_timezone.utc)
            except Exception:
                size = None
                mtime = None

            ext = os.path.splitext(f)[1].lower()
            root_obj = _pick_root(full, roots)

            try:
                _, was_created = Image.objects.get_or_create(
                    path=full,
                    defaults={
                        "filename": f,
                        "size": size,
                        "ext": ext,
                        "file_ext": ext,
                        "mtime": mtime,
                        "root": root_obj,
                    },
                )
            except Exception as e:
                print(f"[scan] DB error on {full}: {e}")
                continue

            if was_created:
                created += 1

            if time.time() - last_log > LOG_EVERY_SECONDS:
                print(
                    f"[scan] dir={dirpath} "
                    f"seen={seen_files} indexable_seen={indexable_seen} created={created} "
                    f"skipped_files={skipped_files} skipped_dirs={skipped_dirs}"
                )
                last_log = time.time()

    print(
        f"[scan] done. "
        f"seen={seen_files} indexable_seen={indexable_seen} created={created} "
        f"skipped_files={skipped_files} skipped_dirs={skipped_dirs}"
    )
    return created