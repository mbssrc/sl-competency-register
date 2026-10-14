import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# The repo root (parent of web/), for seed_taxonomy to find JSON files.
PROJECT_ROOT = BASE_DIR.parent

# Data directory for database files.
DATA_DIR = Path(os.environ.get("PERSONNEL_DATA_DIR", str(BASE_DIR)))

# Source-of-truth JSON tree (taxonomy/, profiles/, services/). Defaults to the
# repo root for development; must be set when the app is installed elsewhere.
TAXONOMY_JSON_DIR = Path(os.environ.get("PERSONNEL_TAXONOMY_DIR", str(PROJECT_ROOT)))

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() in ("true", "1", "yes")

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
# Deployments pass the key as a file (a systemd credential) instead, so it
# stays out of the process environment and the Nix store.
if not SECRET_KEY and os.environ.get("DJANGO_SECRET_KEY_FILE"):
    _key_file = os.environ["DJANGO_SECRET_KEY_FILE"]
    try:
        SECRET_KEY = Path(_key_file).read_text(encoding="utf-8").strip()
    except OSError as e:
        raise ImproperlyConfigured(f"DJANGO_SECRET_KEY_FILE {_key_file}: {e}")
    if not SECRET_KEY:
        raise ImproperlyConfigured(f"DJANGO_SECRET_KEY_FILE {_key_file} is empty.")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-dev-only-change-me-in-production"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false.")

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "django_htmx",
    "axes",
    # Local
    "apps.core",
    "apps.taxonomy",
    "apps.personnel",
    "apps.accounts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.AuditMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "apps.core.context_processors.site",
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Product naming. SITE_NAME is the full name; the two parts let the sidebar
# set the owner above the product so a long name does not wrap awkwardly in a
# 256px column.
SITE_OWNER = "SecLab"
SITE_PRODUCT = "Competence Register"
SITE_NAME = f"{SITE_OWNER} {SITE_PRODUCT}"

WSGI_APPLICATION = "config.wsgi.application"

# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "personnel.sqlite3",
    },
    "taxonomy": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "taxonomy.sqlite3",
    },
}

DATABASE_ROUTERS = ["apps.core.db_router.PersonnelRouter"]

# Custom user model
AUTH_USER_MODEL = "accounts.User"

# Authentication backends
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Password hashers — Argon2 first, then PBKDF2
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

# Login
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"

# Session
SESSION_COOKIE_AGE = 8 * 60 * 60  # 8 hours

# Security
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# Security — transport
TRUSTED_PROXY_COUNT = int(os.environ.get("PERSONNEL_TRUSTED_PROXY_COUNT", "0"))

if TRUSTED_PROXY_COUNT:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

# Request limits
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # 5 MB
DATA_UPLOAD_MAX_NUMBER_FIELDS = 5000  # project_assess matrices are wide
MAX_IMPORT_FILE_SIZE = 5 * 1024 * 1024  # enforced in the import view
MAX_IMPORT_UNCOMPRESSED_SIZE = 20 * 1024 * 1024  # xlsx is a zip: cap what it expands to
MAX_IMPORT_ROWS = 1000  # the taxonomy has ~240 skills

# django-axes
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 0.5  # hours
AXES_LOCKOUT_PARAMETERS = ["ip_address"]
# Same proxy-aware IP as the audit log; django-ipware is not installed, so the
# AXES_IPWARE_* settings would be ignored and axes would see only the proxy.
AXES_CLIENT_IP_CALLABLE = "apps.core.middleware.client_ip"

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Dubai"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "static/"
STATICFILES_DIRS = [
    BASE_DIR / "static" / "dist",
    BASE_DIR / "static" / "vendor",
    BASE_DIR / "static" / "js",
]
STATIC_ROOT = BASE_DIR / "staticfiles"

if not DEBUG:
    STORAGES = {
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "personnel.audit": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": True,
        },
        "axes": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
