from __future__ import annotations

from django.http import JsonResponse
from django.shortcuts import render


def wants_html(request) -> bool:
    accept = request.headers.get("Accept", "")
    return bool(getattr(request, "htmx", False) or "text/html" in accept)


def render_api_response(request, template_name: str, context: dict):
    if wants_html(request):
        return render(request, template_name, context)
    return JsonResponse(context, safe=False if isinstance(context, list) else True)
