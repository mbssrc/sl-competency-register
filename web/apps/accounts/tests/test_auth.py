import pytest
from django.test import Client

from apps.accounts.models import User


@pytest.mark.django_db
class TestUserCreation:
    def test_create_user_default_role(self):
        u = User.objects.create_user(username="testuser", password="testpass123")
        assert u.role == "user"
        assert u.is_admin is False

    def test_create_admin_user(self):
        u = User.objects.create_user(username="admin", password="testpass123", role="admin")
        assert u.role == "admin"
        assert u.is_admin is True

    def test_superuser_gets_admin_role(self):
        u = User.objects.create_superuser(username="super", password="testpass123")
        assert u.role == "admin"
        assert u.is_admin is True


@pytest.mark.django_db
class TestLoginView:
    def test_login_page_renders(self):
        client = Client()
        response = client.get("/accounts/login/")
        assert response.status_code == 200

    def test_login_with_valid_credentials(self):
        User.objects.create_user(username="testuser", password="testpass123")
        client = Client()
        response = client.post(
            "/accounts/login/", {"username": "testuser", "password": "testpass123"}
        )
        assert response.status_code == 302

    def test_login_with_invalid_credentials(self):
        client = Client()
        response = client.post("/accounts/login/", {"username": "bad", "password": "bad"})
        assert response.status_code == 200  # Re-renders form

    def test_logout_redirects_to_login(self):
        user = User.objects.create_user(username="testuser", password="testpass123")
        client = Client()
        client.force_login(user)
        response = client.post("/accounts/logout/")
        assert response.status_code == 302
