from __future__ import annotations

import json
import os
import re
import urllib.request
from django.conf import settings
from collections import Counter, defaultdict
from typing import Any
from uuid import UUID

import torch
from PIL import Image as PILImage
from django.db import models

from .clip_model import get_model
from .models import Folder, Image

QDRANT_URL = getattr(settings, "QDRANT_URL", "http://127.0.0.1:6333").rstrip("/")
COLLECTION = "images"

device = "cpu"

TOKEN_RE = re.compile(r"[a-z0-9]+")


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _qdrant_search_raw(vector: list[float], limit: int = 20) -> list[dict[str, Any]]:
    if not vector:
        return []

    url = f"{QDRANT_URL}/collections/{COLLECTION}/points/search"

    payload = {
        "vector": vector,
        "limit": int(limit or 20),
        "with_payload": True,
        "with_vector": False,
    }

    res = _post_json(url, payload)

    out: list[dict[str, Any]] = []

    for hit in (res.get("result") or []):
        score = float(hit.get("score") or 0.0)
        if score < 0.20:
            continue

        payload = hit.get("payload") or {}

        out.append(
            {
                "score": score,
                "id": str(hit.get("id")),
                "payload": payload,
            }
        )

    return out


def _normalize_text(text: str) -> str:
    return (text or "").strip().lower()


def _tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(_normalize_text(text))


def _dedupe_tokens(tokens: list[str]) -> list[str]:
    seen = set()
    out = []
    for token in tokens:
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _query_tokens(text: str) -> list[str]:
    return _dedupe_tokens(_tokenize(text))


def _is_probable_job_number(token: str) -> bool:
    if not token:
        return False
    if len(token) < 4:
        return False
    return token.isdigit()


def _build_text_blob(img: Image) -> dict[str, str]:
    filename = _normalize_text(img.filename or "")
    path = _normalize_text(img.path or "")
    folder_tokens = _normalize_text(getattr(img, "folder_tokens", "") or "")
    customer_name = _normalize_text(getattr(img, "customer_name", "") or "")
    job_type = _normalize_text(getattr(img, "job_type", "") or "")
    probable_job_number = _normalize_text(getattr(img, "probable_job_number", "") or "")
    extracted_text = _normalize_text(
        getattr(img, "extracted_text", "") or getattr(img, "text", "") or ""
    )

    combined = " ".join(
        [
            filename,
            path,
            folder_tokens,
            customer_name,
            job_type,
            probable_job_number,
            extracted_text,
        ]
    ).strip()

    return {
        "filename": filename,
        "path": path,
        "folder_tokens": folder_tokens,
        "customer_name": customer_name,
        "job_type": job_type,
        "probable_job_number": probable_job_number,
        "extracted_text": extracted_text,
        "combined": combined,
    }


def _token_overlap_score(
    query_tokens: list[str],
    haystack: str,
    per_match: float,
    full_bonus: float = 0.0,
) -> float:
    if not query_tokens or not haystack:
        return 0.0

    matched = sum(1 for token in query_tokens if token in haystack)
    if not matched:
        return 0.0

    score = matched * per_match
    if matched == len(query_tokens):
        score += full_bonus
    return score


def _folder_scope_parts(folder: Folder | None = None, folder_id: int | str | None = None):
    if folder is None and folder_id:
        try:
            folder = Folder.objects.only("id", "root_id", "rel_path").get(id=folder_id)
        except Folder.DoesNotExist:
            return None

    if not folder:
        return None

    prefix = (folder.rel_path or "").strip("/")
    return {
        "root_id": folder.root_id,
        "prefix": prefix,
    }


def _apply_folder_scope_qs(qs, folder: Folder | None = None, folder_id: int | str | None = None):
    scope = _folder_scope_parts(folder=folder, folder_id=folder_id)
    if not scope:
        return qs

    qs = qs.filter(root_id=scope["root_id"])

    prefix = scope["prefix"]
    if not prefix:
        return qs

    return qs.filter(
        models.Q(relative_dir=prefix) |
        models.Q(relative_dir__startswith=prefix + "/")
    )


def _row_in_folder_scope(row: dict[str, Any], scope: dict[str, Any] | None) -> bool:
    if not scope:
        return True

    row_root_id = row.get("root_id")
    if row_root_id != scope["root_id"]:
        return False

    prefix = scope["prefix"]
    if not prefix:
        return True

    rel_dir = ((row.get("relative_dir") or "")).strip("/")
    if rel_dir:
        return rel_dir == prefix or rel_dir.startswith(prefix + "/")

    path = _normalize_text(row.get("path") or "")
    return f"/{prefix.lower()}/" in path or path.endswith("/" + prefix.lower())


def _build_db_candidate_filter(text: str, q_tokens: list[str]):
    filt = models.Q()

    if text:
        filt |= (
            models.Q(filename__icontains=text)
            | models.Q(path__icontains=text)
            | models.Q(folder_tokens__icontains=text)
            | models.Q(customer_name__icontains=text)
            | models.Q(job_type__icontains=text)
            | models.Q(probable_job_number__icontains=text)
            | models.Q(text__icontains=text)
            | models.Q(extracted_text__icontains=text)
        )

    for token in q_tokens:
        filt |= (
            models.Q(filename__icontains=token)
            | models.Q(path__icontains=token)
            | models.Q(folder_tokens__icontains=token)
            | models.Q(customer_name__icontains=token)
            | models.Q(job_type__icontains=token)
            | models.Q(probable_job_number__icontains=token)
            | models.Q(text__icontains=token)
            | models.Q(extracted_text__icontains=token)
        )

    return filt


def _rank_result(
    img: Image,
    query: str,
    vector_score: float | None = None,
    strong_match_folders: set[str] | None = None,
) -> float:
    q = _normalize_text(query)
    q_tokens = _query_tokens(q)
    fields = _build_text_blob(img)

    filename = fields["filename"]
    path = fields["path"]
    folder_tokens = fields["folder_tokens"]
    customer_name = fields["customer_name"]
    job_type = fields["job_type"]
    probable_job_number = fields["probable_job_number"]
    extracted_text = fields["extracted_text"]
    combined = fields["combined"]

    score = float(vector_score or 0.0) * 1.6

    if q:
        if q in filename:
            score += 4.0
        if q in customer_name:
            score += 4.5
        if q in probable_job_number:
            score += 5.5
        if q in folder_tokens:
            score += 3.5
        if q in job_type:
            score += 2.5
        if q in path:
            score += 2.5
        if q in extracted_text:
            score += 1.5
        if q in combined:
            score += 1.0

    score += _token_overlap_score(q_tokens, filename, per_match=1.6, full_bonus=1.0)
    score += _token_overlap_score(q_tokens, customer_name, per_match=2.0, full_bonus=1.5)
    score += _token_overlap_score(q_tokens, probable_job_number, per_match=3.0, full_bonus=2.0)
    score += _token_overlap_score(q_tokens, folder_tokens, per_match=1.4, full_bonus=1.0)
    score += _token_overlap_score(q_tokens, job_type, per_match=1.0, full_bonus=0.5)
    score += _token_overlap_score(q_tokens, path, per_match=0.8, full_bonus=0.5)
    score += _token_overlap_score(q_tokens, extracted_text, per_match=0.35, full_bonus=0.25)

    for token in q_tokens:
        if _is_probable_job_number(token):
            if token == probable_job_number:
                score += 8.0
            elif token in probable_job_number:
                score += 4.0
            elif token in path:
                score += 2.0

    file_ext = _normalize_text(getattr(img, "file_ext", "") or "")
    if file_ext in {".pdf", ".indd", ".psd", ".ai", ".eps"}:
        score += 0.08

    folder = os.path.dirname(path)
    if strong_match_folders and folder in strong_match_folders:
        score += 0.75

    return score


def embed_text(text: str) -> list[float]:
    text = (text or "").strip()
    if not text:
        return []

    model, _preprocess, tokenizer = get_model()
    tokens = tokenizer([text]).to(device)

    with torch.no_grad():
        emb = model.encode_text(tokens)

    emb = emb / emb.norm(dim=-1, keepdim=True)
    return emb[0].float().cpu().tolist()


def embed_uploaded_image(file_obj) -> list[float]:
    import gc

    model, preprocess, _tokenizer = get_model()

    file_obj.seek(0)
    im = PILImage.open(file_obj).convert("RGB")
    image_input = preprocess(im).unsqueeze(0).to(device)

    with torch.no_grad():
        emb = model.encode_image(image_input)

    emb = emb / emb.norm(dim=-1, keepdim=True)
    vector = emb[0].float().cpu().tolist()

    # ---- important cleanup to prevent RAM growth ----
    del emb
    del image_input
    del im
    gc.collect()

    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return vector

def search_text(
    text: str,
    limit: int = 24,
    folder: Folder | None = None,
    folder_id: int | str | None = None,
) -> list[dict[str, Any]]:
    vec = embed_text(text)
    hits = _qdrant_search_raw(vec, limit=max(int(limit or 24) * 4, 80))
    scope = _folder_scope_parts(folder=folder, folder_id=folder_id)

    out: list[dict[str, Any]] = []

    for h in hits:
        payload = h.get("payload") or {}

        row = {
            "score": h["score"],
            "point_id": h["id"],
            "path": payload.get("path"),
            "filename": payload.get("filename"),
            "root_id": payload.get("root_id"),
            "relative_dir": payload.get("relative_dir"),
        }

        if scope and not _row_in_folder_scope(row, scope):
            continue

        out.append(row)

        if len(out) >= int(limit or 24):
            break

    return out


def qdrant_search(vector: list[float], limit: int = 20) -> list[dict[str, Any]]:
    hits = _qdrant_search_raw(vector, limit=int(limit or 20))

    out: list[dict[str, Any]] = []

    for h in hits:
        payload = dict(h.get("payload") or {})
        payload["score"] = h["score"]
        payload["point_id"] = h["id"]
        out.append(payload)

    return out


def hybrid_search(
    text: str,
    limit: int = 24,
    folder: Folder | None = None,
    folder_id: int | str | None = None,
) -> list[dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return []

    limit = int(limit or 24)
    q = _normalize_text(text)
    q_tokens = _query_tokens(q)
    scope = _folder_scope_parts(folder=folder, folder_id=folder_id)

    scores: dict[str, float] = defaultdict(float)
    rows: dict[str, dict[str, Any]] = {}

    semantic_hits = search_text(
        text,
        limit=max(limit * 4, 80),
        folder=folder,
        folder_id=folder_id,
    )
    for rank, hit in enumerate(semantic_hits, start=1):
        point_id = str(hit.get("point_id"))
        if not point_id:
            continue

        semantic_score = float(hit.get("score") or 0.0)

        scores[point_id] += semantic_score * 4.0
        scores[point_id] += max(0.0, 0.75 - (rank * 0.01))

        rows[point_id] = {
            "point_id": point_id,
            "filename": hit.get("filename"),
            "path": hit.get("path"),
            "root_id": hit.get("root_id"),
            "relative_dir": hit.get("relative_dir"),
        }

    db_candidate_filter = _build_db_candidate_filter(text, q_tokens)

    db_qs = Image.objects.filter(indexed=True)
    db_qs = _apply_folder_scope_qs(db_qs, folder=folder, folder_id=folder_id)
    db_qs = (
        db_qs
        .filter(db_candidate_filter)
        .only(
            "id",
            "filename",
            "path",
            "root_id",
            "relative_dir",
            "text",
            "extracted_text",
            "folder_tokens",
            "customer_name",
            "job_type",
            "probable_job_number",
            "file_ext",
        )[: max(limit * 4, 120)]
    )

    for img in db_qs:
        point_id = str(img.id)
        fields = _build_text_blob(img)

        scores[point_id] += 5.0

        if q and q in fields["filename"]:
            scores[point_id] += 7.0
        if q and q in fields["customer_name"]:
            scores[point_id] += 8.0
        if q and q in fields["probable_job_number"]:
            scores[point_id] += 9.0
        if q and q in fields["folder_tokens"]:
            scores[point_id] += 6.0
        if q and q in fields["job_type"]:
            scores[point_id] += 4.0
        if q and q in fields["path"]:
            scores[point_id] += 3.0
        if q and q in fields["extracted_text"]:
            scores[point_id] += 2.0

        scores[point_id] += _token_overlap_score(q_tokens, fields["filename"], per_match=2.0, full_bonus=1.5)
        scores[point_id] += _token_overlap_score(q_tokens, fields["customer_name"], per_match=2.5, full_bonus=2.0)
        scores[point_id] += _token_overlap_score(q_tokens, fields["probable_job_number"], per_match=3.0, full_bonus=2.0)
        scores[point_id] += _token_overlap_score(q_tokens, fields["folder_tokens"], per_match=1.8, full_bonus=1.0)
        scores[point_id] += _token_overlap_score(q_tokens, fields["job_type"], per_match=1.25, full_bonus=0.75)
        scores[point_id] += _token_overlap_score(q_tokens, fields["path"], per_match=1.0, full_bonus=0.5)
        scores[point_id] += _token_overlap_score(q_tokens, fields["extracted_text"], per_match=0.4, full_bonus=0.25)

        for token in q_tokens:
            if _is_probable_job_number(token):
                if token == fields["probable_job_number"]:
                    scores[point_id] += 10.0
                elif token in fields["path"]:
                    scores[point_id] += 2.5

        rows[point_id] = {
            "point_id": point_id,
            "filename": img.filename,
            "path": img.path,
            "root_id": img.root_id,
            "relative_dir": img.relative_dir,
        }

    missing_ids = set()
    for pid in scores.keys():
        if not rows.get(pid, {}).get("filename"):
            try:
                missing_ids.add(UUID(pid))
            except Exception:
                continue

    if missing_ids:
        fill_qs = Image.objects.filter(id__in=list(missing_ids))
        fill_qs = _apply_folder_scope_qs(fill_qs, folder=folder, folder_id=folder_id)

        for img in fill_qs:
            point_id = str(img.id)
            rows[point_id] = {
                "point_id": point_id,
                "filename": img.filename,
                "path": img.path,
                "root_id": img.root_id,
                "relative_dir": img.relative_dir,
            }

    point_ids = set()
    for pid in scores.keys():
        try:
            point_ids.add(UUID(pid))
        except Exception:
            continue

    image_qs = Image.objects.filter(id__in=list(point_ids))
    image_qs = _apply_folder_scope_qs(image_qs, folder=folder, folder_id=folder_id)

    image_map = {
        str(img.id): img
        for img in image_qs.only(
            "id",
            "filename",
            "path",
            "relative_dir",
            "text",
            "extracted_text",
            "folder_tokens",
            "customer_name",
            "job_type",
            "probable_job_number",
            "file_ext",
        )
    }

    ranked = []
    for point_id, base_score in scores.items():
        row = dict(rows.get(point_id) or {})
        img = image_map.get(point_id)

        if scope and not _row_in_folder_scope(row, scope):
            continue

        if img:
            final_score = _rank_result(img, text, vector_score=base_score)
            fields = _build_text_blob(img)
        else:
            final_score = float(base_score or 0.0)
            fields = {}

        labels = []

        if img and q in fields.get("filename", ""):
            labels.append("filename")

        if img and q in fields.get("customer_name", ""):
            labels.append("customer")

        if img and q in fields.get("probable_job_number", ""):
            labels.append("job")

        if img and q in fields.get("folder_tokens", ""):
            labels.append("folder")

        if img and q in fields.get("extracted_text", ""):
            labels.append("ocr")

        if base_score > 0.5:
            labels.append("semantic")

        row["match_labels"] = labels
        row["score"] = round(final_score, 4)
        row["point_id"] = point_id
        ranked.append(row)

    ranked.sort(key=lambda r: r.get("score", 0.0), reverse=True)

    folder_counts = Counter(
        os.path.dirname((row.get("path") or ""))
        for row in ranked[:40]
        if row.get("path")
    )
    strong_match_folders = {
        folder_name for folder_name, count in folder_counts.items()
        if folder_name and count >= 2
    }

    reranked = []
    for row in ranked:
        point_id = row["point_id"]
        img = image_map.get(point_id)
        base_score = scores.get(point_id, 0.0)

        if img:
            final_score = _rank_result(
                img,
                text,
                vector_score=base_score,
                strong_match_folders=strong_match_folders,
            )
        else:
            final_score = float(base_score or 0.0)

        new_row = dict(row)
        new_row["score"] = round(final_score, 4)
        reranked.append(new_row)

    reranked.sort(key=lambda r: r.get("score", 0.0), reverse=True)
    return reranked[:limit]


def qdrant_get_vector(point_id: str) -> list[float] | None:
    url = f"{QDRANT_URL}/collections/{COLLECTION}/points/{point_id}"

    try:
        data = _get_json(url)
    except Exception:
        return None

    result = data.get("result") or {}
    vector = result.get("vector")
    return vector or None


def find_near_duplicates(point_id: str, limit: int = 20, threshold: float = 0.92) -> list[dict[str, Any]]:
    vector = qdrant_get_vector(point_id)
    if not vector:
        return []

    hits = qdrant_search(vector, limit=limit + 10)

    out = []
    for hit in hits:
        pid = str(hit.get("point_id"))
        score = float(hit.get("score") or 0.0)

        if pid == str(point_id):
            continue
        if score < threshold:
            continue

        out.append(hit)

    return out[:limit]


def get_visual_cluster(point_id: str, limit: int = 24) -> list[dict[str, Any]]:
    vector = qdrant_get_vector(point_id)
    if not vector:
        return []

    hits = qdrant_search(vector, limit=max(limit + 12, 40))

    out = []
    for hit in hits:
        pid = str(hit.get("point_id"))
        if pid == str(point_id):
            continue
        out.append(hit)

    return out[:limit]


def discover_clusters(limit: int = 40) -> list[dict[str, Any]]:
    qs = (
        Image.objects.filter(indexed=True)
        .exclude(visual_cluster_id="")
        .values("visual_cluster_id")
        .annotate(count=models.Count("id"))
        .order_by("-count")[:limit]
    )

    return list(qs)


def search_by_folder(
    path: str,
    limit: int = 50,
    folder: Folder | None = None,
    folder_id: int | str | None = None,
) -> list[dict[str, Any]]:
    path = _normalize_text(path)
    if not path and not folder and not folder_id:
        return []

    qs = Image.objects.all()
    qs = _apply_folder_scope_qs(qs, folder=folder, folder_id=folder_id)

    if path:
        qs = qs.filter(path__icontains=path)

    qs = qs.only("id", "filename", "path", "root_id", "relative_dir").order_by("filename")[: limit or 50]

    return [
        {
            "point_id": str(img.id),
            "filename": img.filename,
            "path": img.path,
            "root_id": img.root_id,
            "relative_dir": img.relative_dir,
            "score": 1.0,
        }
        for img in qs
    ]

def _result_field(obj, key: str, default=""):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def detect_match_reasons(img, query: str) -> list[str]:
    if not query:
        return []

    q = query.lower()
    reasons = []

    filename = _result_field(img, "filename", "") or ""
    customer_name = _result_field(img, "customer_name", "") or ""
    probable_job_number = _result_field(img, "probable_job_number", "") or ""
    relative_dir = _result_field(img, "relative_dir", "") or ""
    folder_tokens = _result_field(img, "folder_tokens", "") or ""
    text = _result_field(img, "text", "") or ""
    extracted_text = _result_field(img, "extracted_text", "") or ""
    ocr_text = _result_field(img, "ocr_text", "") or ""
    score = _result_field(img, "score", None)

    if filename and q in filename.lower():
        reasons.append("filename")

    if customer_name and q in customer_name.lower():
        reasons.append("customer")

    if probable_job_number and q in str(probable_job_number).lower():
        reasons.append("job")

    if relative_dir and q in relative_dir.lower():
        reasons.append("folder")
    elif folder_tokens and q in folder_tokens.lower():
        reasons.append("folder")

    text_blob = " ".join([text, extracted_text, ocr_text]).lower()
    if q in text_blob:
        reasons.append("ocr")

    if not reasons and score is not None:
        reasons.append("semantic")

    return reasons

def apply_match_reasons(results, query: str, mode: str):
    """
    Attach match labels to search results.
    """

    if not results:
        return results

    if not query or mode not in {"semantic", "hybrid", "db"}:
        for img in results:
            if isinstance(img, dict):
                img["match_labels"] = []
            else:
                img.match_labels = []
        return results

    for img in results:
        labels = detect_match_reasons(img, query)

        if isinstance(img, dict):
            img["match_labels"] = labels
        else:
            img.match_labels = labels

    return results