from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional

from django.db import close_old_connections

from indexer.models import Image
from indexer.qdrant import client, COLLECTION, ensure_collection


@dataclass
class WorkItem:
    id: str
    path: str
    filename: str


@dataclass
class WorkResult:
    id: str
    ok: bool
    vector: Optional[list[float]] = None
    error: Optional[str] = None


def _worker(item: WorkItem) -> WorkResult:
    """
    Runs in a separate process.
    Generates preview + embeds it. Does NOT touch Django ORM or Qdrant.
    """
    try:
        from indexer.previews import generate_preview
        from indexer.clip_embedder import embed_image

        preview = generate_preview(item.path)
        if not preview:
            return WorkResult(id=item.id, ok=False, error="preview failed")

        vec = embed_image(preview)
        return WorkResult(id=item.id, ok=True, vector=vec)

    except Exception as e:
        return WorkResult(id=item.id, ok=False, error=str(e))


def run_index_parallel(batch_size: int = 500, workers: int = 2):
    """
    Pull a batch of unindexed items, fan out preview+embed, then upsert+mark indexed.
    """
    ensure_collection()

    # Important before forking: close DB connections so children don’t inherit them
    close_old_connections()

    qs = Image.objects.filter(indexed=False).only("id", "path", "filename")[:batch_size]
    items = [WorkItem(id=str(img.id), path=img.path, filename=img.filename) for img in qs]

    if not items:
        print("No pending items.")
        return

    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_worker, it) for it in items]

        for fut in as_completed(futures):
            res: WorkResult = fut.result()

            if not res.ok or not res.vector:
                print("Failed:", res.id, res.error)
                continue

            # Upsert to Qdrant (main process)
            img = Image.objects.get(id=res.id)

            client.upsert(
                collection_name=COLLECTION,
                points=[
                    {
                        "id": str(img.id),
                        "vector": res.vector,
                        "payload": {
                            "path": img.path,
                            "filename": img.filename,
                        },
                    }
                ],
            )

            img.indexed = True
            img.save(update_fields=["indexed"])

            print("Indexed:", img.filename)