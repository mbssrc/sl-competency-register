"""Parsing and validation for values read straight off request.POST.

The views in this project read request data directly rather than through
ModelForms, so these helpers are the single place the proficiency range and
the choice/date/JSON formats are defined. Each raises ValidationError with a
message fit to show a user.
"""

import datetime
import json

from django.core.exceptions import ValidationError

# The proficiency model in taxonomy/_meta.json: 0 (None) .. 5 (Authority).
LEVEL_MIN = 0
LEVEL_MAX = 5


def parse_bounded_int(raw, field_name, minimum, maximum, default=None):
    """Parse an integer and require it to fall within an inclusive range."""
    text = "" if raw is None else str(raw).strip()
    if not text:
        if default is None:
            raise ValidationError(f"{field_name} is required.")
        return default

    try:
        value = int(text)
    except (TypeError, ValueError):
        raise ValidationError(f"{field_name} must be a number, got {text!r}.")

    if not (minimum <= value <= maximum):
        raise ValidationError(f"{field_name} must be between {minimum} and {maximum}, got {value}.")
    return value


def parse_level(raw, field_name="level", default=None):
    """Parse a proficiency level, accepting the Excel export's "3 — Label" form."""
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)  # a numeric spreadsheet cell
    text = "" if raw is None else str(raw).strip()
    # The self-assessment workbook writes "3 — Independent"; take the leading number.
    head = text.split()[0] if text else text
    return parse_bounded_int(head, field_name, LEVEL_MIN, LEVEL_MAX, default=default)


def parse_date(raw, field_name):
    """Parse an ISO-8601 date (what <input type="date"> submits)."""
    text = "" if raw is None else str(raw).strip()
    if not text:
        raise ValidationError(f"{field_name} is required.")
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise ValidationError(f"{field_name} must be a date in YYYY-MM-DD form, got {text!r}.")


def parse_choice(raw, field_name, choices, default=None):
    """Require a value to be one of a Django-style [(value, label), ...] list."""
    text = "" if raw is None else str(raw).strip()
    if not text:
        if default is None:
            raise ValidationError(f"{field_name} is required.")
        return default

    valid = {value for value, _label in choices}
    if text not in valid:
        raise ValidationError(
            f"{field_name} must be one of {', '.join(sorted(valid))}, got {text!r}."
        )
    return text


def parse_json_object(raw, field_name):
    """Parse a JSON object from a textarea; a blank field means an empty object."""
    text = "" if raw is None else str(raw).strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValidationError(f"{field_name} is not valid JSON: {e.msg} (line {e.lineno}).")
    if not isinstance(value, dict):
        raise ValidationError(f"{field_name} must be a JSON object ({{...}}).")
    return value
