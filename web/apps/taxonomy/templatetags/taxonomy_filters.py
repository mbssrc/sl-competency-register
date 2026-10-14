from django import template

register = template.Library()


@register.filter
def first_sentence(value):
    """Return the first sentence of a string (up to the first period followed by a space or end)."""
    if not value:
        return ""
    idx = value.find(". ")
    if idx == -1:
        # No ". " found — try trailing period
        return value.rstrip(".") if value.endswith(".") else value
    return value[: idx + 1]
