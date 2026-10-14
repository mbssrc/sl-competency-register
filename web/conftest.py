from django.conf import settings


def pytest_configure():
    # Use plain static files storage during tests (no manifest needed).
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
