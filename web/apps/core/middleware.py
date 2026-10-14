import logging

from django.conf import settings
from django.contrib.auth.signals import user_login_failed
from django.dispatch import receiver

logger = logging.getLogger("personnel.audit")


def client_ip(request):
    """Return the originating client IP.

    Behind a reverse proxy REMOTE_ADDR is the proxy, so every request looks
    like it comes from 127.0.0.1 — which would make the django-axes IP
    lockout and any fail2ban jail useless. X-Forwarded-For is only trusted
    when TRUSTED_PROXY_COUNT says a proxy is actually in front of us,
    because a client can otherwise set that header freely.
    """
    proxy_count = settings.TRUSTED_PROXY_COUNT
    if proxy_count:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if len(hops) >= proxy_count:
            return hops[-proxy_count]
    return request.META.get("REMOTE_ADDR", "unknown")


# Every line ends with from=<client>: the fail2ban filter anchors on it, and
# client-supplied fields (path, username) are logged with %r so an encoded
# newline or a fake "from=" cannot forge a line or frame another address.
@receiver(user_login_failed)
def log_failed_login(sender, credentials, request=None, **kwargs):
    if request is None:
        return
    logger.warning(
        "personnel-auth: FAILED login user=%r from=%s",
        credentials.get("username", ""),
        client_ip(request),
    )


AUDITED_READ_PREFIXES = ("/personnel",)
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        ip = client_ip(request)
        user = getattr(request, "user", None)
        authenticated = bool(user and user.is_authenticated)
        username = user.username if authenticated else "anonymous"

        # Every successful mutation, anywhere in the app. The taxonomy is the
        # controlled document here, so its edits must be traceable too.
        if (
            request.method in MUTATING_METHODS
            and authenticated
            and 200 <= response.status_code < 400
        ):
            logger.info(
                "personnel-auth: CHANGE user=%s method=%s path=%r status=%s from=%s",
                username,
                request.method,
                request.path,
                response.status_code,
                ip,
            )

        if (
            authenticated
            and request.method == "GET"
            and request.path.startswith(AUDITED_READ_PREFIXES)
            and response.status_code == 200
        ):
            logger.info(
                "personnel-auth: ACCESS user=%s path=%r from=%s",
                username,
                request.path,
                ip,
            )

        if response.status_code == 403:
            logger.warning(
                "personnel-auth: FORBIDDEN user=%s method=%s path=%r from=%s",
                username,
                request.method,
                request.path,
                ip,
            )

        return response
