"""Settings for the test suite.

Production defaults (DEBUG off, secure cookies, HSTS) apply, with a throwaway
signing key so settings.py's fail-closed check passes. SSL redirect is off
because the test client speaks plain HTTP.
"""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-insecure-key")

from .settings import *  # noqa: E402,F401,F403

SECURE_SSL_REDIRECT = False
