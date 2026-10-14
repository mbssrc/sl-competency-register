import pytest
from django.test import Client

from apps.core.middleware import client_ip


class TestClientIp:
    def test_uses_remote_addr_when_not_proxied(self, rf, settings):
        settings.TRUSTED_PROXY_COUNT = 0
        request = rf.get("/", REMOTE_ADDR="203.0.113.7")
        assert client_ip(request) == "203.0.113.7"

    def test_uses_forwarded_for_when_proxied(self, rf, settings):
        """The trusted proxy appends the peer it saw as the rightmost hop;
        anything left of that was supplied by the client and is spoofable."""
        settings.TRUSTED_PROXY_COUNT = 1
        request = rf.get(
            "/",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.7",
        )
        assert client_ip(request) == "203.0.113.7"

    def test_axes_uses_client_ip(self, rf, settings):
        """django-ipware is not installed, so without AXES_CLIENT_IP_CALLABLE
        axes would lock out the proxy's address instead of the client's."""
        from axes.helpers import get_client_ip_address

        settings.TRUSTED_PROXY_COUNT = 1
        request = rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="203.0.113.7")
        assert get_client_ip_address(request) == "203.0.113.7"

    def test_falls_back_when_header_absent(self, rf, settings):
        settings.TRUSTED_PROXY_COUNT = 1
        request = rf.get("/", REMOTE_ADDR="127.0.0.1")
        assert client_ip(request) == "127.0.0.1"

    def test_ignores_forwarded_for_when_untrusted(self, rf, settings):
        """A spoofed header must not be believed when no proxy is configured."""
        settings.TRUSTED_PROXY_COUNT = 0
        request = rf.get("/", REMOTE_ADDR="203.0.113.7", HTTP_X_FORWARDED_FOR="1.2.3.4")
        assert client_ip(request) == "203.0.113.7"


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestHealthEndpoint:
    def test_health_ok_does_not_leak_detail(self):
        response = Client().get("/health/")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestSecretKeyFile:
    """Production reads the key from a file (a systemd credential), so it
    never appears in the unit's environment or the Nix store."""

    def _secret_key(self, tmp_path, **env):
        import os
        import subprocess
        import sys
        from pathlib import Path

        web = Path(__file__).resolve().parents[3]
        base = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "PERSONNEL_"))}
        return subprocess.run(
            [sys.executable, "-c", "from config import settings; print(settings.SECRET_KEY)"],
            cwd=web,
            env={**base, "PERSONNEL_DATA_DIR": str(tmp_path), **env},
            capture_output=True,
            text=True,
        )

    def test_reads_key_from_file(self, tmp_path):
        key_file = tmp_path / "secret_key"
        key_file.write_text("k" * 64 + "\n")
        result = self._secret_key(tmp_path, DJANGO_SECRET_KEY_FILE=str(key_file))
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "k" * 64

    def test_empty_key_file_fails_closed(self, tmp_path):
        key_file = tmp_path / "secret_key"
        key_file.write_text("")
        result = self._secret_key(tmp_path, DJANGO_SECRET_KEY_FILE=str(key_file))
        assert result.returncode != 0
        assert "ImproperlyConfigured" in result.stderr

    def test_missing_key_file_fails_closed(self, tmp_path):
        result = self._secret_key(tmp_path, DJANGO_SECRET_KEY_FILE=str(tmp_path / "absent"))
        assert result.returncode != 0
        assert "ImproperlyConfigured" in result.stderr
