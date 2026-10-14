import pytest
from django.core.management import call_command
from django.test import Client

from apps.accounts.models import User


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestExcelExport:
    @pytest.fixture(autouse=True)
    def setup(self):
        call_command("seed_taxonomy", verbosity=0)
        self.admin = User.objects.create_user(username="admin", password="p", role="admin")
        self.user = User.objects.create_user(username="user", password="p", role="user")

    def test_export_page_requires_admin(self):
        client = Client()
        client.force_login(self.user)
        response = client.get("/export/")
        assert response.status_code == 403

    def test_export_page_accessible_to_admin(self):
        client = Client()
        client.force_login(self.admin)
        response = client.get("/export/")
        assert response.status_code == 200

    def test_taxonomy_xlsx_download(self):
        client = Client()
        client.force_login(self.admin)
        response = client.get("/export/taxonomy.xlsx")
        assert response.status_code == 200
        assert "spreadsheetml" in response["Content-Type"]

    def test_personnel_xlsx_download(self):
        client = Client()
        client.force_login(self.admin)
        response = client.get("/export/personnel.xlsx")
        assert response.status_code == 200
        assert "spreadsheetml" in response["Content-Type"]

    def test_reports_xlsx_download(self):
        client = Client()
        client.force_login(self.admin)
        response = client.get("/export/reports.xlsx")
        assert response.status_code == 200
        assert "spreadsheetml" in response["Content-Type"]
