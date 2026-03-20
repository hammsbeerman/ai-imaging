from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.crypto import constant_time_compare


def _is_trusted_proxy_request(request) -> bool:
    expected = (getattr(settings, "STUDIO_PROXY_SHARED_SECRET", "") or "").strip()
    provided = (request.META.get("HTTP_X_STUDIO_PROXY_SECRET", "") or "").strip()
    return bool(expected and provided and constant_time_compare(provided, expected))


class TrustedProxyCsrfBypassMiddleware:
    """
    Runs before CsrfViewMiddleware.
    If the request came from Studio Management with the shared secret,
    bypass CSRF so proxied POST/HTMX actions work.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        trusted = _is_trusted_proxy_request(request)
        request._studio_proxy_trusted = trusted
        if trusted:
            request._dont_enforce_csrf_checks = True
        return self.get_response(request)


class TrustedProxyUserMiddleware:
    """
    Runs after AuthenticationMiddleware.
    If the request came from Studio Management with the shared secret,
    attach a local authenticated user so @login_required AI views work.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(request, "_studio_proxy_trusted", False):
            user_model = get_user_model()
            username = getattr(settings, "STUDIO_PROXY_USERNAME", "studio_proxy")

            user, created = user_model.objects.get_or_create(
                username=username,
                defaults={
                    "is_active": True,
                    "is_staff": True,
                },
            )

            if not user.is_active:
                user.is_active = True
                user.save(update_fields=["is_active"])

            request.user = user

        return self.get_response(request)