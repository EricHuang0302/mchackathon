"""The YAML subset rule documents are allowed to use."""

from __future__ import annotations

import pytest

from app.services.rules.errors import RestrictedYamlError
from app.services.rules.restricted_yaml import load_restricted_yaml, normalize_source


def load(text: str):
    return load_restricted_yaml(text, source="test")


def detail_of(text: str) -> str:
    with pytest.raises(RestrictedYamlError) as excinfo:
        load(text)
    return excinfo.value.detail or ""


def test_supported_subset_parses():
    document = load(
        "ruleVersion: \"demo-v1\"\n"
        "enabled: true\n"
        "disabled: false\n"
        "missing: null\n"
        "count: -12\n"
        "nested:\n"
        "  items:\n"
        "    - one\n"
        "    - two\n"
    )
    assert document == {
        "ruleVersion": "demo-v1",
        "enabled": True,
        "disabled": False,
        "missing": None,
        "count": -12,
        "nested": {"items": ["one", "two"]},
    }


def test_duplicate_key_at_the_top_level_is_rejected():
    assert detail_of("ruleVersion: \"a\"\nruleVersion: \"b\"\n") == "duplicate_key"


def test_duplicate_key_nested_two_levels_deep_is_rejected():
    text = (
        "states:\n"
        "  - id: \"cpr\"\n"
        "    instruction:\n"
        "      templateId: \"one\"\n"
        "      templateId: \"two\"\n"
    )
    assert detail_of(text) == "duplicate_key"


def test_alias_is_rejected():
    text = "base: &anchor\n  a: 1\ncopy: *anchor\n"
    # The anchor is refused before the alias can be reached.
    assert detail_of(text) in ("anchor_not_supported", "alias_not_supported")


def test_merge_key_is_rejected():
    assert detail_of("a:\n  \"<<\": {}\n") == "merge_key_not_supported"


def test_non_string_key_is_rejected():
    assert detail_of("1: one\n") == "non_string_key"


@pytest.mark.parametrize("scalar", ["yes", "no", "on", "off", "True", "FALSE", "y"])
def test_yaml_1_1_boolean_spellings_are_rejected_or_kept_as_strings(scalar: str):
    """Only lowercase true / false are booleans; nothing else silently becomes one."""
    try:
        document = load(f"value: {scalar}\n")
    except RestrictedYamlError as exc:
        assert exc.detail == "ambiguous_boolean"
    else:
        assert document["value"] == scalar


@pytest.mark.parametrize("scalar", ["0x1f", "0o17", "007", "+1", "1_000", "1:30"])
def test_ambiguous_integer_spellings_are_rejected_or_kept_as_strings(scalar: str):
    try:
        document = load(f"value: {scalar}\n")
    except RestrictedYamlError as exc:
        assert exc.detail == "ambiguous_integer"
    else:
        assert document["value"] == scalar


@pytest.mark.parametrize("scalar", ["1.5", ".inf", ".nan"])
def test_floats_are_rejected(scalar: str):
    try:
        document = load(f"intervalMs: {scalar}\n")
    except RestrictedYamlError as exc:
        assert exc.detail == "float_not_supported"
    else:
        assert document["intervalMs"] == scalar


@pytest.mark.parametrize("scalar", ["~", "Null", "NULL", ""])
def test_ambiguous_null_spellings_are_rejected(scalar: str):
    assert detail_of(f"value: {scalar}\n") == "ambiguous_null"


def test_explicit_null_is_accepted():
    assert load("noticeTemplateId: null\n") == {"noticeTemplateId": None}


@pytest.mark.parametrize(
    "text",
    [
        "value: !!set\n  ? a\n",
        "value: !!binary aGk=\n",
        "value: !!python/object/apply:os.system [echo]\n",
    ],
)
def test_unsupported_tags_are_rejected(text: str):
    assert detail_of(text) == "parse_error"


def test_unquoted_date_is_not_silently_converted_to_a_timestamp():
    assert detail_of("observedAt: 2026-09-19\n") == "parse_error"


def test_multiple_documents_are_rejected():
    assert detail_of("a: 1\n---\nb: 2\n") == "multiple_documents"


def test_non_mapping_root_is_rejected():
    assert detail_of("- a\n- b\n") == "invalid_root"


def test_normalize_source_strips_bom_and_normalizes_line_endings():
    assert normalize_source("\ufeffa: 1\r\nb: 2\r") == "a: 1\nb: 2\n"
