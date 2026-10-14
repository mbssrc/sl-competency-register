import pytest
from django.core.management import call_command
from django.test import Client

from apps.accounts.models import User


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestDashboard:
    def test_dashboard_shows_stats(self):
        call_command("seed_taxonomy", verbosity=0)
        user = User.objects.create_user(username="test", password="test123")
        client = Client()
        client.force_login(user)
        response = client.get("/")
        assert response.status_code == 200
        # Should show skill count somewhere
        assert b"231" in response.content or b"Skills" in response.content


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestNavigationSectionTitles:
    """The sidebar's section titles must use each mode's own ink.

    They used text-gray-400 dark:text-gray-500, which is the pairing inverted:
    gray-400 is the palette's dark-mode secondary ink and gray-500 its
    light-mode one, so each mode was handed the other's colour. That measured
    2.01:1 on the light sidebar and 2.65:1 on the dark one.
    """

    SECTIONS = ("Overview", "Taxonomy", "Reports", "Admin")

    def nav(self):
        call_command("seed_taxonomy", verbosity=0)
        # Admin, so the Admin section renders alongside the others.
        user = User.objects.create_user(
            username="navadmin", password="strong-pass-here", role="admin"
        )
        client = Client()
        client.force_login(user)
        return client.get("/").content.decode()

    def title_tag(self, html, section):
        i = html.index(f">{section}</span>")
        return html[html.rindex("<span", 0, i) : i]

    def test_section_titles_use_the_ink_matching_each_mode(self):
        html = self.nav()
        for section in self.SECTIONS:
            tag = self.title_tag(html, section)
            assert "text-gray-600" in tag, f"{section}: light-mode ink wrong: {tag}"
            assert "dark:text-gray-400" in tag, f"{section}: dark-mode ink wrong: {tag}"

    def test_section_titles_avoid_the_inverted_pairing(self):
        html = self.nav()
        for section in self.SECTIONS:
            tag = self.title_tag(html, section)
            assert "text-gray-400 " not in tag, f"{section} uses the dark ink on light"
            assert "dark:text-gray-500" not in tag, f"{section} uses the light ink on dark"

    def test_inactive_nav_icons_are_visible_in_both_modes(self):
        """The icons beside each item had the same inverted pairing as the
        titles, which left them at 2.01:1 and 2.65:1 against a 3:1 threshold
        for graphical objects."""
        html = self.nav()

        assert "text-gray-400 dark:text-gray-500" not in html


@pytest.mark.django_db(databases=["default", "taxonomy"])
class TestDashboardTileLinks:
    """Each metric tile must lead somewhere that explains its own number."""

    def manager_dashboard(self):
        call_command("seed_taxonomy", verbosity=0)
        user = User.objects.create_user(
            username="tilemgr", password="strong-pass-here", role="manager"
        )
        client = Client()
        client.force_login(user)
        return client.get("/").content.decode()

    def tile_href(self, html, label):
        """The href of the <a> wrapping the tile carrying this label."""
        i = html.index(f">{label}</div>")
        a = html.rindex("<a href=", 0, i)
        return html[a + len('<a href="') : html.index('"', a + len('<a href="'))]

    def test_staffing_gaps_tile_leads_to_the_gap_analysis(self):
        """It used to point at the project list, the same place the Open
        Projects tile beside it already went, so the number had nowhere of its
        own to explain itself."""
        html = self.manager_dashboard()

        assert self.tile_href(html, "Staffing Gaps") == "/personnel/gaps/"

    def test_no_two_tiles_share_a_destination(self):
        html = self.manager_dashboard()
        labels = ["Personnel", "Open Projects", "Staffing Gaps", "Skills"]
        hrefs = [self.tile_href(html, label) for label in labels]

        assert len(set(hrefs)) == len(hrefs), dict(zip(labels, hrefs))
