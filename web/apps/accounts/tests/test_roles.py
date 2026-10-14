import datetime

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory

from apps.accounts.decorators import admin_required, owner_or_role, role_required
from apps.accounts.models import User


@role_required("user")
def any_user_view(request):
    return HttpResponse("OK")


@role_required("manager")
def manager_view(request):
    return HttpResponse("OK")


@role_required("admin")
def admin_view(request):
    return HttpResponse("OK")


@admin_required
def legacy_admin_view(request):
    return HttpResponse("OK")


@owner_or_role("manager")
def person_scoped_view(request, person_id):
    return HttpResponse("OK")


@pytest.fixture
def factory():
    return RequestFactory()


@pytest.fixture
def make_user(db):
    def _make(role):
        return User.objects.create_user(
            username=f"u-{role}", password="strong-pass-here", role=role
        )

    return _make


@pytest.mark.django_db
class TestRoleRank:
    def test_ranks_are_ordered(self):
        assert User.ROLE_RANK["user"] < User.ROLE_RANK["manager"] < User.ROLE_RANK["admin"]

    def test_manager_is_in_choices(self):
        assert "manager" in dict(User.ROLE_CHOICES)

    @pytest.mark.parametrize(
        "role,is_admin,is_manager",
        [
            ("user", False, False),
            ("manager", False, True),
            ("admin", True, True),
        ],
    )
    def test_role_properties(self, make_user, role, is_admin, is_manager):
        user = make_user(role)
        assert user.is_admin is is_admin
        assert user.is_manager is is_manager

    def test_superuser_is_forced_to_admin(self, db):
        user = User.objects.create_superuser(username="root", password="strong-pass-here", email="")
        assert user.role == "admin"

    def test_unknown_role_ranks_lowest(self, make_user):
        """A value left behind by an old migration must not grant access."""
        user = make_user("user")
        user.role = "privileged"  # the name 0003 removed
        assert user.role_rank == -1
        assert user.is_manager is False


@pytest.mark.django_db
class TestRoleRequired:
    def test_anonymous_redirects_with_next(self, factory):
        request = factory.get("/secret/")
        request.user = AnonymousUser()
        response = admin_view(request)
        assert response.status_code == 302
        assert "next=/secret/" in response.url

    @pytest.mark.parametrize("role", ["user", "manager", "admin"])
    def test_user_threshold_admits_everyone(self, factory, make_user, role):
        request = factory.get("/t/")
        request.user = make_user(role)
        assert any_user_view(request).status_code == 200

    @pytest.mark.parametrize(
        "role,expected",
        [
            ("user", 403),
            ("manager", 200),
            ("admin", 200),
        ],
    )
    def test_manager_threshold(self, factory, make_user, role, expected):
        request = factory.get("/t/")
        request.user = make_user(role)
        assert manager_view(request).status_code == expected

    @pytest.mark.parametrize(
        "role,expected",
        [
            ("user", 403),
            ("manager", 403),
            ("admin", 200),
        ],
    )
    def test_admin_threshold(self, factory, make_user, role, expected):
        request = factory.get("/t/")
        request.user = make_user(role)
        assert admin_view(request).status_code == expected

    def test_legacy_admin_required_still_works(self, factory, make_user):
        request = factory.get("/t/")
        request.user = make_user("manager")
        assert legacy_admin_view(request).status_code == 403
        request.user = make_user("admin")
        assert legacy_admin_view(request).status_code == 200

    def test_inactive_user_is_refused(self, factory, make_user):
        user = make_user("admin")
        user.is_active = False
        user.save()
        request = factory.get("/t/")
        request.user = user
        assert admin_view(request).status_code == 403

    def test_rejects_an_unknown_minimum_role(self):
        with pytest.raises(ValueError):
            role_required("wizard")

    def test_decorators_tag_their_threshold(self):
        assert admin_view._required_role == "admin"
        assert manager_view._required_role == "manager"
        assert person_scoped_view._required_role == "manager"


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestOwnerOrRole:
    @pytest.fixture
    def linked(self, db, make_user):
        from apps.personnel.models import Person

        person = Person.objects.create(
            id="JD01",
            name="Jane Doe",
            domains=[],
            start_date=datetime.date(2024, 1, 15),
        )
        user = make_user("user")
        user.person = person
        user.save()
        return user

    def test_owner_may_act_on_their_own_record(self, factory, linked):
        request = factory.get("/t/")
        request.user = linked
        assert person_scoped_view(request, person_id="JD01").status_code == 200

    def test_owner_may_not_act_on_someone_else(self, factory, linked):
        request = factory.get("/t/")
        request.user = linked
        assert person_scoped_view(request, person_id="AB02").status_code == 403

    def test_manager_may_act_on_anyone(self, factory, make_user):
        request = factory.get("/t/")
        request.user = make_user("manager")
        assert person_scoped_view(request, person_id="AB02").status_code == 200

    def test_unlinked_user_may_not_act_on_anyone(self, factory, make_user):
        """person is nullable; an unlinked account must not match by accident."""
        request = factory.get("/t/")
        request.user = make_user("user")
        assert request.user.person_id is None
        assert person_scoped_view(request, person_id="").status_code == 403
        assert person_scoped_view(request, person_id=None).status_code == 403
