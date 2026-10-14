import logging

import pytest
from django.core.management import call_command
from django.http import HttpResponse, HttpResponseForbidden
from django.test import Client, RequestFactory

from apps.accounts.models import User
from apps.core.middleware import AuditMiddleware


@pytest.mark.django_db
class TestAuditMiddleware:
    @pytest.fixture
    def factory(self):
        return RequestFactory()

    def test_logs_personnel_access(self, factory, caplog):
        mw = AuditMiddleware(lambda req: HttpResponse("ok"))
        request = factory.get("/personnel/PERS-001/")
        request.user = User.objects.create_user(username="priv", password="p", role="user")
        request.META["REMOTE_ADDR"] = "10.0.0.50"
        with caplog.at_level(logging.INFO, logger="personnel.audit"):
            mw(request)
        assert any("ACCESS" in r.message for r in caplog.records)
        assert any("10.0.0.50" in r.message for r in caplog.records)

    def test_logs_403_responses(self, factory, caplog):
        mw = AuditMiddleware(lambda req: HttpResponseForbidden("denied"))
        request = factory.get("/admin/")
        request.user = User.objects.create_user(username="u", password="p", role="user")
        request.META["REMOTE_ADDR"] = "10.0.0.50"
        with caplog.at_level(logging.WARNING, logger="personnel.audit"):
            mw(request)
        assert any("FORBIDDEN" in r.message for r in caplog.records)

    def test_does_not_log_non_personnel_access(self, factory, caplog):
        mw = AuditMiddleware(lambda req: HttpResponse("ok"))
        request = factory.get("/taxonomy/NETSEC/")
        request.user = User.objects.create_user(username="u2", password="p", role="user")
        request.META["REMOTE_ADDR"] = "10.0.0.50"
        with caplog.at_level(logging.INFO, logger="personnel.audit"):
            mw(request)
        assert not any("ACCESS" in r.message for r in caplog.records)


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestAuditCoverage:
    def test_logs_taxonomy_writes(self, caplog):
        call_command("seed_taxonomy", verbosity=0)
        manager = User.objects.create_user(
            username="lead", password="strong-pass-here", role="manager"
        )
        client = Client()
        client.force_login(manager)

        with caplog.at_level(logging.INFO, logger="personnel.audit"):
            client.post(
                "/taxonomy/skill/NETSEC-RECON-PORTSCANNING/edit/",
                {"name": "Renamed", "description": "d", "status": "active"},
            )

        messages = [r.getMessage() for r in caplog.records]
        assert any("CHANGE" in m and "/taxonomy/" in m and "lead" in m for m in messages)

    def test_does_not_log_reads_outside_personnel(self, caplog):
        call_command("seed_taxonomy", verbosity=0)
        user = User.objects.create_user(username="viewer", password="strong-pass-here", role="user")
        client = Client()
        client.force_login(user)

        with caplog.at_level(logging.INFO, logger="personnel.audit"):
            client.get("/taxonomy/")

        assert not any("CHANGE" in r.getMessage() for r in caplog.records)
        assert not any("ACCESS" in r.getMessage() for r in caplog.records)

    def test_logs_personnel_reads_as_access(self, caplog, db):
        import datetime

        from apps.personnel.models import Person

        person = Person.objects.create(
            id="JD01",
            name="Jane Doe",
            domains=[],
            start_date=datetime.date(2024, 1, 15),
        )
        user = User.objects.create_user(username="jane", password="strong-pass-here", role="user")
        user.person = person
        user.save()
        client = Client()
        client.force_login(user)

        with caplog.at_level(logging.INFO, logger="personnel.audit"):
            client.get("/personnel/JD01/")

        assert any("ACCESS" in r.getMessage() for r in caplog.records)

    def test_logs_a_refusal_with_the_method(self, caplog, db):
        user = User.objects.create_user(username="nosy", password="strong-pass-here", role="user")
        client = Client()
        client.force_login(user)

        with caplog.at_level(logging.WARNING, logger="personnel.audit"):
            client.get("/personnel/gaps/")

        assert any(
            "FORBIDDEN" in r.getMessage() and "nosy" in r.getMessage() for r in caplog.records
        )


@pytest.mark.django_db
class TestFail2banLogLines:
    """fail2ban bans the address in the trailing ``from=`` field, so that
    field must be the real client and nothing a client sends may forge it."""

    def test_logs_failed_login_with_client_address(self, caplog):
        client = Client(REMOTE_ADDR="10.0.0.77")
        with caplog.at_level(logging.WARNING, logger="personnel.audit"):
            client.post("/accounts/login/", {"username": "ghost", "password": "wrong"})
        messages = [r.getMessage() for r in caplog.records]
        assert any(
            m.startswith("personnel-auth: FAILED login") and m.endswith("from=10.0.0.77")
            for m in messages
        )

    def test_failed_login_username_cannot_forge_a_line(self, caplog):
        client = Client(REMOTE_ADDR="10.0.0.77")
        with caplog.at_level(logging.WARNING, logger="personnel.audit"):
            client.post(
                "/accounts/login/",
                {
                    "username": "x from=10.9.9.9\npersonnel-auth: FAILED login from=10.9.9.9",
                    "password": "wrong",
                },
            )
        failed = [r.getMessage() for r in caplog.records if "FAILED" in r.getMessage()]
        assert failed
        assert all("\n" not in m and m.endswith("from=10.0.0.77") for m in failed)

    def test_forbidden_path_cannot_forge_the_address(self, caplog):
        mw = AuditMiddleware(lambda req: HttpResponseForbidden("denied"))
        # Percent-encoded, as a real client would send it; Django decodes it.
        request = RequestFactory().get("/x%20from=10.9.9.9%0AFORBIDDEN%20from=10.9.9.9")
        assert "\n" in request.path
        request.user = User.objects.create_user(username="u", password="p")
        request.META["REMOTE_ADDR"] = "10.0.0.50"
        with caplog.at_level(logging.WARNING, logger="personnel.audit"):
            mw(request)
        messages = [r.getMessage() for r in caplog.records]
        assert messages
        assert all("\n" not in m and m.endswith("from=10.0.0.50") for m in messages)
