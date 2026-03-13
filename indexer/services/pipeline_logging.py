import traceback

from indexer.tasklog import log


def log_stage_start(stage: str, img) -> None:
    log(stage, f"start image_id={img.id} file={img.filename} path={img.path}")


def log_stage_ok(stage: str, img, extra: str = "") -> None:
    msg = f"ok image_id={img.id} file={img.filename}"
    if extra:
        msg += f" {extra}"
    log(stage, msg)


def log_stage_skip(stage: str, img, reason: str) -> None:
    log(stage, f"skipped image_id={img.id} file={img.filename} reason={reason}")


def log_stage_error(stage: str, img, exc: Exception) -> None:
    log(
        stage,
        f"FAILED image_id={img.id} file={img.filename} path={img.path} error={str(exc)[:500]}",
        "ERROR",
    )
    tb = traceback.format_exc().strip()
    if tb:
        log(stage, tb[-4000:], "ERROR")