"""Checks over the template sources themselves."""

import re
from pathlib import Path

TEMPLATES = [
    p
    for p in Path(__file__).resolve().parents[3].rglob("*.html")
    if "node_modules" not in str(p) and "staticfiles" not in str(p)
]


def test_no_multiline_django_comments():
    """`{# #}` is single-line only; spanning lines renders it to the page.

    Django's lexer matches {# ... #} within one line. A multi-line one is not a
    comment at all: the text lands in the rendered HTML, which is how two
    explanatory notes ended up visible above the navigation and every page
    header. Multi-line notes belong in {% comment %} ... {% endcomment %}.
    """
    offenders = []
    for path in TEMPLATES:
        text = path.read_text()
        for match in re.finditer(r"\{#", text):
            close = text.find("#}", match.start())
            if close != -1 and "\n" in text[match.start() : close]:
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{path.name}:{line}")
    assert not offenders, (
        "multi-line {# #} comments render as page text; use "
        f"{{% comment %}}: {', '.join(offenders)}"
    )


def test_div_tags_balance_in_every_template():
    """A dropped </div> silently reflows a page without failing any test.

    One did: a regex that moved the service readiness summary consumed the
    closing tag of its first tile, so the label wrapped the number. Counting
    is crude but catches exactly that class of edit.
    """
    offenders = []
    for path in TEMPLATES:
        text = path.read_text()
        diff = len(re.findall(r"<div\b", text)) - len(re.findall(r"</div>", text))
        if diff:
            offenders.append(f"{path.name} ({diff:+d})")
    assert not offenders, f"unbalanced <div> tags: {', '.join(offenders)}"


def test_the_product_name_is_not_hardcoded_in_templates():
    """The name lives in settings.SITE_NAME and reaches templates through a
    context processor. It used to be typed into 24 files, which is why the
    rename touched all of them."""
    offenders = [
        p.name
        for p in TEMPLATES
        if "SecLab Competence Register" in p.read_text() or "SecLab Team" in p.read_text()
    ]
    # site_name is Django's own context key on the login view, where it
    # resolves to the request host rather than the product.
    offenders += [p.name for p in TEMPLATES if "{{ site_name }}" in p.read_text()]
    assert not offenders, (
        "hardcoded product name; use {{ site_name }} / {{ site_product }}: "
        f"{', '.join(sorted(set(offenders)))}"
    )
