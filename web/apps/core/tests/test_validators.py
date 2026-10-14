import datetime

import pytest
from django.core.exceptions import ValidationError

from apps.core.validators import (
    LEVEL_MAX,
    LEVEL_MIN,
    parse_bounded_int,
    parse_choice,
    parse_date,
    parse_json_object,
    parse_level,
)

STATUS_CHOICES = [("planning", "Planning"), ("done", "Done")]


class TestParseLevel:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (0, 0),
            (5, 5),
            ("3", 3),
            (" 4 ", 4),
            ("3 — Independent", 3),
            ("0 - None", 0),
            (3.0, 3),  # a numeric spreadsheet cell
        ],
    )
    def test_accepts_valid_levels(self, raw, expected):
        assert parse_level(raw) == expected

    @pytest.mark.parametrize("raw", [-1, 6, 999, "6", "-1"])
    def test_rejects_out_of_range(self, raw):
        with pytest.raises(ValidationError) as exc:
            parse_level(raw)
        assert "between 0 and 5" in str(exc.value)

    @pytest.mark.parametrize("raw", ["", None, "abc", "Level 3", [], {}])
    def test_rejects_non_numeric(self, raw):
        with pytest.raises(ValidationError):
            parse_level(raw)

    def test_message_names_the_field(self):
        with pytest.raises(ValidationError) as exc:
            parse_level("9", field_name="self-assessed level")
        assert "self-assessed level" in str(exc.value)

    def test_bounds_are_exported(self):
        assert (LEVEL_MIN, LEVEL_MAX) == (0, 5)


class TestParseBoundedInt:
    def test_accepts_in_range(self):
        assert parse_bounded_int("7", "method count", 0, 50) == 7

    def test_uses_default_for_blank(self):
        assert parse_bounded_int("", "method count", 0, 50, default=3) == 3

    def test_rejects_above_maximum(self):
        with pytest.raises(ValidationError):
            parse_bounded_int("1000000000", "method count", 0, 50)

    def test_rejects_non_numeric(self):
        with pytest.raises(ValidationError):
            parse_bounded_int("lots", "method count", 0, 50)


class TestParseDate:
    def test_accepts_iso_date(self):
        assert parse_date("2026-06-01", "assessed date") == datetime.date(2026, 6, 1)

    @pytest.mark.parametrize("raw", ["", None, "01/06/2026", "2026-13-45", "yesterday"])
    def test_rejects_invalid(self, raw):
        with pytest.raises(ValidationError) as exc:
            parse_date(raw, "assessed date")
        assert "assessed date" in str(exc.value)


class TestParseChoice:
    def test_accepts_listed_value(self):
        assert parse_choice("done", "status", STATUS_CHOICES) == "done"

    def test_rejects_unlisted_value(self):
        with pytest.raises(ValidationError) as exc:
            parse_choice("active", "status", STATUS_CHOICES)
        assert "active" in str(exc.value)

    def test_uses_default_for_blank(self):
        assert parse_choice("", "status", STATUS_CHOICES, default="planning") == "planning"

    def test_rejects_blank_without_default(self):
        with pytest.raises(ValidationError):
            parse_choice("", "status", STATUS_CHOICES)


class TestParseJsonObject:
    def test_blank_is_empty_object(self):
        assert parse_json_object("  ", "mappings") == {}

    def test_parses_nested_object(self):
        raw = '{"nice": {"tks": ["K0018"]}, "cwe": ["CWE-79"], "flag": true}'
        assert parse_json_object(raw, "mappings") == {
            "nice": {"tks": ["K0018"]},
            "cwe": ["CWE-79"],
            "flag": True,
        }

    @pytest.mark.parametrize("raw", ["{not json", '{"a": 1,}'])
    def test_rejects_invalid_json(self, raw):
        with pytest.raises(ValidationError) as exc:
            parse_json_object(raw, "mappings")
        assert "mappings is not valid JSON" in exc.value.messages[0]

    @pytest.mark.parametrize("raw", ['["K0018"]', '"K0018"', "42"])
    def test_rejects_non_object(self, raw):
        with pytest.raises(ValidationError) as exc:
            parse_json_object(raw, "mappings")
        assert "must be a JSON object" in exc.value.messages[0]
