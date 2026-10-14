import pytest
from django.test import Client

from apps.accounts.models import User


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestAdminTools:
    def _make_admin(self):
        user = User.objects.create_user(username="admin", password="test123", role="admin")
        client = Client()
        client.force_login(user)
        return client, user

    def _make_regular(self):
        user = User.objects.create_user(username="regular", password="test123", role="user")
        client = Client()
        client.force_login(user)
        return client, user

    def test_requires_admin_role(self):
        client, _ = self._make_regular()
        response = client.get("/admin-tools/")
        assert response.status_code == 403

    def test_admin_can_access(self):
        client, _ = self._make_admin()
        response = client.get("/admin-tools/")
        assert response.status_code == 200
        assert b"Seed Taxonomy" in response.content
        assert b"Integrity Check" in response.content

    def test_seed_command_runs(self):
        client, _ = self._make_admin()
        response = client.post("/admin-tools/seed/")
        assert response.status_code == 200
        assert b"Seed Taxonomy" in response.content

    def test_export_json_runs(self, settings, tmp_path):
        settings.TAXONOMY_JSON_DIR = tmp_path
        client, _ = self._make_admin()
        response = client.post("/admin-tools/export-json/")
        assert response.status_code == 200
        assert b"Export Taxonomy" in response.content
        assert (tmp_path / "taxonomy" / "_meta.json").exists()

    def test_integrity_check_runs(self):
        client, _ = self._make_admin()
        response = client.post("/admin-tools/check-integrity/")
        assert response.status_code == 200
        assert b"Integrity Check" in response.content

    def test_seed_requires_post(self):
        client, _ = self._make_admin()
        response = client.get("/admin-tools/seed/")
        assert response.status_code == 405

    def test_export_requires_post(self):
        client, _ = self._make_admin()
        response = client.get("/admin-tools/export-json/")
        assert response.status_code == 405

    def test_integrity_requires_post(self):
        client, _ = self._make_admin()
        response = client.get("/admin-tools/check-integrity/")
        assert response.status_code == 405


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestUserManagement:
    def _make_admin(self):
        user = User.objects.create_user(username="admin", password="test123", role="admin")
        client = Client()
        client.force_login(user)
        return client, user

    def test_user_list_requires_admin(self):
        user = User.objects.create_user(username="regular", password="test123", role="user")
        client = Client()
        client.force_login(user)
        response = client.get("/users/")
        assert response.status_code == 403

    def test_user_list_shows_users(self):
        client, admin = self._make_admin()
        User.objects.create_user(username="testuser", password="test123", role="user")
        response = client.get("/users/")
        assert response.status_code == 200
        assert b"testuser" in response.content
        assert b"admin" in response.content

    def test_create_user(self):
        client, _ = self._make_admin()
        response = client.post(
            "/users/create/",
            {
                "username": "newuser",
                "email": "new@example.com",
                "password": "correct-horse-battery",
                "role": "user",
            },
        )
        assert response.status_code == 302
        new_user = User.objects.get(username="newuser")
        assert new_user.role == "user"
        assert new_user.email == "new@example.com"

    def test_create_user_form_get(self):
        client, _ = self._make_admin()
        response = client.get("/users/create/")
        assert response.status_code == 200
        assert b"Create User" in response.content
        assert b'x-data="combobox"' in response.content

    def test_create_user_modal_person_picker_is_searchable(self):
        client, _ = self._make_admin()
        response = client.get("/users/create/", HTTP_HX_REQUEST="true")
        assert b'x-data="combobox"' in response.content
        assert b'name="person"' in response.content
        assert b"data-search" not in response.content  # people have no tags

    def test_create_user_duplicate_username(self):
        client, _ = self._make_admin()
        response = client.post(
            "/users/create/",
            {
                "username": "admin",
                "password": "secret123",
                "role": "user",
            },
        )
        assert response.status_code == 200
        assert b"Username already exists" in response.content

    def test_edit_user_role(self):
        client, _ = self._make_admin()
        target = User.objects.create_user(username="target", password="test123", role="user")
        response = client.post(
            f"/users/{target.id}/edit/",
            {"email": "t@example.com", "role": "admin"},
        )
        assert response.status_code == 302
        target.refresh_from_db()
        assert target.role == "admin"

    def test_edit_user_form_get(self):
        client, _ = self._make_admin()
        target = User.objects.create_user(username="target", password="test123", role="user")
        response = client.get(f"/users/{target.id}/edit/")
        assert response.status_code == 200
        assert b"Edit User" in response.content

    def test_toggle_active(self):
        client, _ = self._make_admin()
        target = User.objects.create_user(username="target", password="test123", role="user")
        assert target.is_active is True

        response = client.post(f"/users/{target.id}/toggle-active/")
        assert response.status_code == 302
        target.refresh_from_db()
        assert target.is_active is False

        # Toggle back
        response = client.post(f"/users/{target.id}/toggle-active/")
        assert response.status_code == 302
        target.refresh_from_db()
        assert target.is_active is True

    def test_toggle_active_requires_post(self):
        client, _ = self._make_admin()
        target = User.objects.create_user(username="target", password="test123", role="user")
        response = client.get(f"/users/{target.id}/toggle-active/")
        assert response.status_code == 405

    def test_create_rejects_weak_password(self):
        admin_client, _ = self._make_admin()
        response = admin_client.post(
            "/users/create/",
            {"username": "weakling", "password": "1", "role": "user"},
        )
        assert response.status_code == 200
        assert b"too short" in response.content.lower()
        assert not User.objects.filter(username="weakling").exists()

    def test_create_rejects_numeric_password(self):
        admin_client, _ = self._make_admin()
        response = admin_client.post(
            "/users/create/",
            {"username": "numeric", "password": "84729163", "role": "user"},
        )
        assert response.status_code == 200
        assert b"entirely numeric" in response.content.lower()
        assert not User.objects.filter(username="numeric").exists()

    def test_create_accepts_strong_password(self):
        admin_client, _ = self._make_admin()
        response = admin_client.post(
            "/users/create/",
            {"username": "sturdy", "password": "correct-horse-battery", "role": "user"},
        )
        assert response.status_code == 302
        assert User.objects.filter(username="sturdy").exists()

    def test_edit_rejects_weak_password_and_keeps_the_old_one(self):
        admin_client, _ = self._make_admin()
        target = User.objects.create_user(
            username="target", password="original-strong-pass", role="user"
        )
        response = admin_client.post(
            f"/users/{target.id}/edit/",
            {"email": "t@example.com", "role": "user", "password": "1"},
        )
        assert response.status_code == 200
        target.refresh_from_db()
        assert target.check_password("original-strong-pass")


@pytest.mark.django_db
class TestAdminLockoutGuards:
    def test_cannot_deactivate_own_account(self):
        admin = User.objects.create_user(username="boss", password="strong-pass-here", role="admin")
        User.objects.create_user(username="deputy", password="strong-pass-here", role="admin")
        client = Client()
        client.force_login(admin)
        response = client.post(f"/users/{admin.id}/toggle-active/")
        admin.refresh_from_db()
        assert admin.is_active is True
        assert response.status_code == 302

    def test_cannot_deactivate_the_last_admin(self):
        admin = User.objects.create_user(username="only", password="strong-pass-here", role="admin")
        other = User.objects.create_user(
            username="other", password="strong-pass-here", role="admin"
        )
        client = Client()
        client.force_login(other)
        client.post(f"/users/{admin.id}/toggle-active/")  # leaves `other` as the only one
        client.post(f"/users/{other.id}/toggle-active/")
        other.refresh_from_db()
        assert other.is_active is True

    def test_cannot_demote_the_last_admin(self):
        admin = User.objects.create_user(username="only", password="strong-pass-here", role="admin")
        client = Client()
        client.force_login(admin)
        response = client.post(
            f"/users/{admin.id}/edit/",
            {"email": "a@example.com", "role": "user"},
        )
        assert response.status_code == 200
        admin.refresh_from_db()
        assert admin.role == "admin"

    def test_can_demote_an_admin_when_another_remains(self):
        admin = User.objects.create_user(username="boss", password="strong-pass-here", role="admin")
        deputy = User.objects.create_user(
            username="deputy", password="strong-pass-here", role="admin"
        )
        client = Client()
        client.force_login(admin)
        response = client.post(
            f"/users/{deputy.id}/edit/",
            {"email": "d@example.com", "role": "user"},
        )
        assert response.status_code == 302
        deputy.refresh_from_db()
        assert deputy.role == "user"

    def test_can_deactivate_another_user(self):
        admin = User.objects.create_user(username="boss", password="strong-pass-here", role="admin")
        target = User.objects.create_user(
            username="target", password="strong-pass-here", role="user"
        )
        client = Client()
        client.force_login(admin)
        client.post(f"/users/{target.id}/toggle-active/")
        target.refresh_from_db()
        assert target.is_active is False
