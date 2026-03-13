import re
from collections import defaultdict

from django.db.models import Q

from indexer.models import Image
from indexer.search import search_text
from indexer.services.image_service import build_image_summary
from indexer.services.permission_service import filter_images_for_user

FILTER_RE = re.compile(r"(?P<key>customer|ext|before|after|path):(?P<value>[^\s]+)", re.IGNORECASE)
TOKEN_RE = re.compile(r"[a-z0-9]+")


def _normalize_text(value: str) -> str:
    return (value or "").strip().lower()


def _tokenize(value: str) -> list[str]:
    return TOKEN_RE.findall(_normalize_text(value))


def _dedupe_tokens(tokens: list[str]) -> list[str]:
    seen = set()
    out = []
    for token in tokens:
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _query_tokens(value: str) -> list[str]:
    return _dedupe_tokens(_tokenize(value))


def _is_probable_job_number(token: str) -> bool:
    return bool(token and len(token) >= 4 and token.isdigit())


def parse_search_query(q: str) -> dict:
    q = (q or "").strip()
    filters = {}
    consumed = []

    for match in FILTER_RE.finditer(q):
        key = match.group("key").lower()
        value = match.group("value").strip()
        filters[key] = value
        consumed.append(match.group(0))

    free_text = q
    for part in consumed:
        free_text = free_text.replace(part, " ")

    free_text = re.sub(r"\s+", " ", free_text).strip()

    return {
        "raw": q,
        "text": free_text,
        "filters": filters,
        "tokens": _query_tokens(free_text),
    }


def _apply_filters(qs, filters: dict):
    customer = filters.get("customer")
    if customer:
        qs = qs.filter(customer_name__icontains=customer)

    ext = filters.get("ext")
    if ext:
        if not ext.startswith("."):
            ext = "." + ext
        qs = qs.filter(file_ext__iexact=ext)

    path = filters.get("path")
    if path:
        qs = qs.filter(path__icontains=path)

    before = filters.get("before")
    if before:
        qs = qs.filter(mtime__lt=before)

    after = filters.get("after")
    if after:
        qs = qs.filter(mtime__gt=after)

    return qs


def _text_blob(img) -> dict[str, str]:
    filename = _normalize_text(img.filename or "")
    path = _normalize_text(img.path or "")
    folder_tokens = _normalize_text(getattr(img, "folder_tokens", "") or "")
    customer_name = _normalize_text(getattr(img, "customer_name", "") or "")
    job_type = _normalize_text(getattr(img, "job_type", "") or "")
    probable_job_number = _normalize_text(getattr(img, "probable_job_number", "") or "")
    extracted_text = _normalize_text(getattr(img, "extracted_text", "") or "")

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


def _score_image(img, q: str, tokens: list[str], semantic_score: float = 0.0) -> float:
    fields = _text_blob(img)
    score = float(semantic_score or 0.0) * 1.8

    if q:
        if q in fields["filename"]:
            score += 6.0
        if q in fields["customer_name"]:
            score += 7.0
        if q in fields["probable_job_number"]:
            score += 8.0
        if q in fields["folder_tokens"]:
            score += 5.5
        if q in fields["job_type"]:
            score += 3.0
        if q in fields["path"]:
            score += 2.5
        if q in fields["extracted_text"]:
            score += 1.5

    for token in tokens:
        if token in fields["filename"]:
            score += 1.6
        if token in fields["customer_name"]:
            score += 2.25
        if token in fields["probable_job_number"]:
            score += 2.75
        if token in fields["folder_tokens"]:
            score += 1.5
        if token in fields["job_type"]:
            score += 1.0
        if token in fields["path"]:
            score += 0.8
        if token in fields["extracted_text"]:
            score += 0.3

        if _is_probable_job_number(token):
            if token == fields["probable_job_number"]:
                score += 8.0
            elif token in fields["path"]:
                score += 2.0

    if tokens:
        matched = 0
        for token in tokens:
            if token in fields["combined"]:
                matched += 1
        if matched == len(tokens):
            score += 2.0
        elif matched:
            score += (matched / len(tokens)) * 1.0

    return score


def hybrid_search_for_user(user, q, limit=50, filters=None):
    parsed = parse_search_query(q)
    merged_filters = dict(parsed["filters"])
    if filters:
        merged_filters.update(filters)

    text = parsed["text"]
    tokens = parsed["tokens"]
    limit = max(1, min(int(limit or 50), 200))

    base_qs = filter_images_for_user(Image.objects.all(), user)
    base_qs = _apply_filters(base_qs, merged_filters)

    db_qs = base_qs
    if text:
        db_filter = (
            Q(filename__icontains=text)
            | Q(path__icontains=text)
            | Q(folder_tokens__icontains=text)
            | Q(customer_name__icontains=text)
            | Q(job_type__icontains=text)
            | Q(probable_job_number__icontains=text)
            | Q(extracted_text__icontains=text)
        )
        for token in tokens:
            db_filter |= Q(filename__icontains=token)
            db_filter |= Q(path__icontains=token)
            db_filter |= Q(folder_tokens__icontains=token)
            db_filter |= Q(customer_name__icontains=token)
            db_filter |= Q(job_type__icontains=token)
            db_filter |= Q(probable_job_number__icontains=token)
            db_filter |= Q(extracted_text__icontains=token)

        db_qs = db_qs.filter(db_filter)

    db_qs = db_qs.only(
        "id",
        "filename",
        "path",
        "file_ext",
        "indexed",
        "preview_status",
        "text_status",
        "embedding_status",
        "customer_name",
        "job_type",
        "folder_tokens",
        "probable_job_number",
        "extracted_text",
    )[: max(limit * 4, 80)]

    semantic_scores = defaultdict(float)
    if text:
        semantic_hits = search_text(text, limit=max(limit * 4, 80))
        for rank, hit in enumerate(semantic_hits, start=1):
            pid = str(hit.get("point_id"))
            if not pid:
                continue
            semantic_scores[pid] += float(hit.get("score") or 0.0) * 3.5
            semantic_scores[pid] += max(0.0, 0.75 - (rank * 0.01))

    results_by_id = {}

    for img in db_qs:
        pid = str(img.id)
        results_by_id[pid] = {
            "img": img,
            "score": _score_image(img, _normalize_text(text), tokens, semantic_scores.get(pid, 0.0)),
        }

    if semantic_scores:
        missing_ids = [pid for pid in semantic_scores.keys() if pid not in results_by_id]
        if missing_ids:
            semantic_qs = filter_images_for_user(
                Image.objects.filter(id__in=missing_ids),
                user,
            ).only(
                "id",
                "filename",
                "path",
                "file_ext",
                "indexed",
                "preview_status",
                "text_status",
                "embedding_status",
                "customer_name",
                "job_type",
                "folder_tokens",
                "probable_job_number",
                "extracted_text",
            )

            for img in semantic_qs:
                pid = str(img.id)
                results_by_id[pid] = {
                    "img": img,
                    "score": _score_image(img, _normalize_text(text), tokens, semantic_scores.get(pid, 0.0)),
                }

    ordered = sorted(
        results_by_id.values(),
        key=lambda row: row["score"],
        reverse=True,
    )[:limit]

    out = []
    for row in ordered:
        summary = build_image_summary(row["img"], score=round(row["score"], 4))
        out.append(summary)

    return out


def similar_search_for_user(user, image_id, limit=24):
    img = filter_images_for_user(Image.objects.filter(id=image_id), user).first()
    if not img:
        return []

    seed = " ".join(
        [
            img.filename.rsplit(".", 1)[0],
            getattr(img, "customer_name", "") or "",
            getattr(img, "job_type", "") or "",
            getattr(img, "probable_job_number", "") or "",
            getattr(img, "folder_tokens", "") or "",
        ]
    ).strip()

    return hybrid_search_for_user(
        user,
        q=seed,
        limit=limit + 1,
    )[:limit]


def duplicates_for_user(user, image_id, limit=24):
    img = filter_images_for_user(Image.objects.filter(id=image_id), user).first()
    if not img:
        return []

    qs = filter_images_for_user(
        Image.objects.filter(
            filename__iexact=img.filename,
            size=img.size,
        ).exclude(id=img.id),
        user,
    ).order_by("filename")[:limit]

    return [build_image_summary(x) for x in qs]


def cluster_for_user(user, image_id, limit=24):
    return similar_search_for_user(user, image_id, limit=limit)