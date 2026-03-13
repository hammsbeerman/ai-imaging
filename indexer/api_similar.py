from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from indexer.models import Image
from indexer.clip_embedder import embed_image
from indexer.qdrant import client, COLLECTION
from indexer.services.image_service import build_image_summary
from indexer.services.permission_service import filter_images_for_user
from indexer.previews import abs_preview_path


@login_required
def similar(request, image_id):
    limit = int(request.GET.get("limit", 25) or 25)
    limit = max(1, min(limit, 100))

    qs = filter_images_for_user(Image.objects.all(), request.user)
    img = get_object_or_404(qs, id=image_id)

    source_path = abs_preview_path(img.preview_path) or img.path
    if not source_path:
        return JsonResponse({
            "ok": True,
            "image_id": str(img.id),
            "count": 0,
            "results": [],
        })

    vec = embed_image(source_path)

    if hasattr(vec, "tolist"):
        vec = vec.tolist()

    res = client.query_points(
        collection_name=COLLECTION,
        query=vec,
        limit=limit + 1,
        with_payload=True,
    )

    point_ids = []
    scores_by_id = {}

    for p in res.points:
        pid = str(p.id)
        if pid == str(img.id):
            continue
        point_ids.append(pid)
        scores_by_id[pid] = float(p.score)

    allowed_matches = filter_images_for_user(
        Image.objects.filter(id__in=point_ids),
        request.user,
    )

    images_by_id = {str(x.id): x for x in allowed_matches}

    results = []
    for pid in point_ids:
        match = images_by_id.get(pid)
        if not match:
            continue
        results.append(build_image_summary(match, score=scores_by_id.get(pid)))

    return JsonResponse({
        "ok": True,
        "image_id": str(img.id),
        "count": len(results[:limit]),
        "results": results[:limit],
    })