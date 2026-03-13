from django.http import JsonResponse

from indexer.services.health_service import get_health_summary


def api_health_summary(request):
    return JsonResponse(get_health_summary())