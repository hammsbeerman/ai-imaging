from django.http import JsonResponse

from indexer.services.search_service import hybrid_search_for_user


def api_search(request):
    q = request.GET.get("q", "").strip()
    limit = int(request.GET.get("limit", 50) or 50)
    limit = max(1, min(limit, 200))

    results = hybrid_search_for_user(request.user, q=q, limit=limit)

    return JsonResponse({
        "ok": True,
        "query": q,
        "count": len(results),
        "results": results,
    })