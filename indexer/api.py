import mimetypes
import os

from django.db.models import Q
from django.http import FileResponse, Http404
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from qdrant_client.models import FieldCondition, Filter, MatchAny

from indexer.clip_text import embed_text
from indexer.models import Image, IndexerSettings, UserAccessRoot
from indexer.open_links import build_smb_folder, build_unc_folder, folder_rel
from indexer.preview_health import preview_files_exist
from indexer.previews import abs_preview_path
from indexer.qdrant import COLLECTION, client, ensure_collection


def _allowed_root_ids(user) -> list[int]:
    if getattr(user, "is_superuser", False):
        return list(
            Image.objects.exclude(root__isnull=True)
            .values_list("root_id", flat=True)
            .distinct()
        )
    return list(UserAccessRoot.objects.filter(user=user).values_list("root_id", flat=True))


def _open_folder_links_for(img: Image, settings: IndexerSettings):
    if img.root_id and img.root:
        unc_base = img.root.open_folder_unc_base or settings.open_folder_unc_base
        smb_base = img.root.open_folder_smb_base or settings.open_folder_smb_base
        scan_base = img.root.scan_path_root
    else:
        unc_base = settings.open_folder_unc_base
        smb_base = settings.open_folder_smb_base
        scan_base = settings.scan_path

    rel_folder = folder_rel(scan_base, img.path)

    return {
        "open_folder_unc": build_unc_folder(unc_base, rel_folder) if unc_base else None,
        "open_folder_smb": build_smb_folder(smb_base, rel_folder) if smb_base else None,
    }


def _best_preview_path(img: Image) -> str | None:
    candidates = [
        abs_preview_path(img.thumb_path),
        abs_preview_path(img.preview_path),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


@api_view(["GET"])
@authentication_classes([TokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def thumb(request, image_id):
    allowed = set(_allowed_root_ids(request.user))

    try:
        img = Image.objects.select_related("root").get(id=image_id)
    except Image.DoesNotExist:
        raise Http404("not found")

    if img.root_id and allowed and img.root_id not in allowed and not request.user.is_superuser:
        raise Http404("not found")

    if img.preview_status == "ok" and not preview_files_exist(img):
        img.preview_status = "pending"
        img.preview_path = ""
        img.thumb_path = ""
        img.preview_error = "Preview file missing; reset for regeneration"
        img.save(update_fields=["preview_status", "preview_path", "thumb_path", "preview_error"])

    preview = _best_preview_path(img)

    if not preview and img.path and os.path.exists(img.path):
        preview = img.path

    if not preview:
        raise Http404("no preview")

    content_type, _ = mimetypes.guess_type(preview)
    if not content_type:
        content_type = "application/octet-stream"

    resp = FileResponse(open(preview, "rb"), content_type=content_type)
    resp["Cache-Control"] = "public, max-age=86400"
    return resp


@api_view(["GET"])
@authentication_classes([TokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def search(request):
    settings = IndexerSettings.load()

    q = (request.GET.get("q") or "").strip()
    limit = int(request.GET.get("limit") or 25)
    text_limit = int(request.GET.get("text_limit") or 25)
    vec_limit = int(request.GET.get("vec_limit") or 50)

    if not q:
        return Response({"q": q, "results": []})

    allowed = set(_allowed_root_ids(request.user))

    text_qs = Image.objects.select_related("root").filter(
        Q(filename__icontains=q)
        | Q(path__icontains=q)
        | Q(text__icontains=q)
        | Q(extracted_text__icontains=q)
    )

    if not request.user.is_superuser and allowed:
        text_qs = text_qs.filter(root_id__in=allowed)

    text_qs = text_qs.only(
        "id",
        "path",
        "filename",
        "root_id",
        "thumb_path",
        "preview_path",
    )[:text_limit]

    results_by_id = {}

    for img in text_qs:
        links = _open_folder_links_for(img, settings)
        results_by_id[str(img.id)] = {
            "id": str(img.id),
            "score": None,
            "text_score": 1.0,
            "path": img.path,
            "filename": img.filename,
            "thumb": f"/api/thumb/{img.id}",
            "sources": ["text"],
            "hybrid_score": 0.15,
            **links,
        }

    ensure_collection()
    vec = embed_text(q)

    qfilter = None
    if not request.user.is_superuser and allowed:
        qfilter = Filter(
            must=[
                FieldCondition(
                    key="root_id",
                    match=MatchAny(any=list(allowed)),
                )
            ]
        )

    res = client.query_points(
        collection_name=COLLECTION,
        query=vec,
        limit=vec_limit,
        with_payload=True,
        query_filter=qfilter,
    )

    points = getattr(res, "points", []) or []

    ids = []
    point_map = {}
    for p in points:
        pid = str(p.id)
        ids.append(pid)
        point_map[pid] = p

    db_images = {
        str(img.id): img
        for img in Image.objects.select_related("root").filter(id__in=ids)
    }

    for pid in ids:
        img = db_images.get(pid)
        p = point_map.get(pid)
        if not img or not p:
            continue

        score = float(getattr(p, "score", 0.0) or 0.0)
        links = _open_folder_links_for(img, settings)

        if pid in results_by_id:
            results_by_id[pid]["score"] = score
            results_by_id[pid]["sources"] = sorted(
                set(results_by_id[pid]["sources"] + ["vector"])
            )
            results_by_id[pid]["hybrid_score"] = max(
                results_by_id[pid]["hybrid_score"],
                score,
            )
        else:
            results_by_id[pid] = {
                "id": str(img.id),
                "score": score,
                "text_score": None,
                "path": img.path,
                "filename": img.filename,
                "thumb": f"/api/thumb/{img.id}",
                "sources": ["vector"],
                "hybrid_score": score,
                **links,
            }

    results = sorted(
        results_by_id.values(),
        key=lambda x: (
            x["hybrid_score"] if x["hybrid_score"] is not None else 0,
            x["text_score"] if x["text_score"] is not None else 0,
        ),
        reverse=True,
    )[:limit]

    return Response(
        {
            "q": q,
            "count": len(results),
            "results": results,
        }
    )