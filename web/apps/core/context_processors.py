"""Template context available on every page."""

from django.conf import settings


def site(request):
    """The product's name, in one place.

    It appears in the sidebar, the login card and every page's <title>. Having
    the templates read it from here means renaming it is a one-line change
    rather than an edit to two dozen files.
    """
    # Not "site_name": django.contrib.auth's LoginView injects that key
    # itself, and view context overrides a context processor.
    return {
        "product_name": settings.SITE_NAME,
        "product_owner": settings.SITE_OWNER,
        "product_title": settings.SITE_PRODUCT,
    }
