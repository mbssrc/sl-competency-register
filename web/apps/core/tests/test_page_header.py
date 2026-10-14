"""Every content page gets the same masthead, from base.html.

Pages used to hand-roll their own header, which is how nine of them ended up
with a breadcrumb and thirteen without. The layout lives in base.html now and
pages only declare the content, so the trail cannot be forgotten.
"""

import pytest
from django.core.management import call_command
from django.test import Client

from apps.accounts.models import User

# The pages reachable without creating any records first.
PAGES = [
    "/",
    "/personnel/",
    "/personnel/projects/",
    "/personnel/gaps/",
    "/personnel/readiness/",
    "/taxonomy/",
    "/taxonomy/profiles/",
    "/taxonomy/services/",
    "/export/",
    "/admin-tools/",
    "/users/",
]


@pytest.fixture
def admin_client(db):
    call_command("seed_taxonomy", verbosity=0)
    user = User.objects.create_user(
        username="headeradmin", password="strong-pass-here", role="admin"
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db(databases=["default", "taxonomy"])
@pytest.mark.parametrize("url", PAGES)
class TestMasthead:
    def test_page_has_a_single_h1_title(self, admin_client, url):
        html = admin_client.get(url).content.decode()
        assert html.count("<h1") == 1, f"{url} has {html.count('<h1')} <h1> elements"

    def test_page_has_a_breadcrumb_trail(self, admin_client, url):
        html = admin_client.get(url).content.decode()
        assert 'aria-label="Breadcrumb"' in html, f"{url} has no breadcrumb"

    def test_page_closes_its_header_with_the_accent_rule(self, admin_client, url):
        html = admin_client.get(url).content.decode()
        assert "data-masthead-rule" in html, f"{url} is missing the header rule"


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestMastheadOptOut:
    def test_the_login_page_has_no_masthead(self):
        html = Client().get("/accounts/login/").content.decode()
        assert "data-masthead-rule" not in html
        assert 'aria-label="Breadcrumb"' not in html


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestDomainPagesAreUniform:
    def test_no_domain_shows_an_attack_tiers_sidebar(self, admin_client):
        """Hardware Security was the only domain carrying attack_tiers data, so
        it alone rendered a second column and looked unlike its siblings. The
        classification is still in the taxonomy and the model; it just no
        longer makes one domain's page a different shape."""
        from apps.taxonomy.models import Domain

        for domain in Domain.objects.using("taxonomy").all():
            html = admin_client.get(f"/taxonomy/{domain.id}/").content.decode()
            assert "Attack Tiers" not in html, f"{domain.id} renders an Attack Tiers sidebar"
