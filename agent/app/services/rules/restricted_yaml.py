"""Restricted YAML loading for rule documents.

Rule content is data, never code. This loader accepts a deliberately small YAML
subset so that the Python and TypeScript interpreters read identical values from
identical bytes, and so that nothing in a rule file can be executed:

* no anchors, aliases, or merge keys;
* no tags beyond plain mappings, sequences, strings, integers, booleans, null
  (timestamps, binary, sets, omap, and pairs are rejected too);
* no duplicate mapping keys, at any nesting depth;
* no non-string mapping keys;
* no floats, which removes formatting divergence between runtimes;
* no implicitly ambiguous scalars. Only ``true`` / ``false`` are booleans, only
  ``null`` is null, and integers must match ``-?(0|[1-9][0-9]*)`` so that YAML
  1.1 spellings such as ``yes``, ``~``, ``0o17``, ``0x1f``, ``007``, ``1_000``,
  and ``1:30`` are refused rather than silently reinterpreted.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from .errors import RestrictedYamlError

_INTEGER_RE = re.compile(r"^-?(0|[1-9][0-9]*)$")

_FORBIDDEN_TAGS = (
    "tag:yaml.org,2002:timestamp",
    "tag:yaml.org,2002:binary",
    "tag:yaml.org,2002:set",
    "tag:yaml.org,2002:omap",
    "tag:yaml.org,2002:pairs",
    "tag:yaml.org,2002:value",
    "tag:yaml.org,2002:merge",
)


def normalize_source(text: str) -> str:
    """Strip a byte-order mark and normalize line endings to ``\\n``.

    Applied before parsing and before hashing so a Windows checkout and a Linux
    checkout of the same package produce the same content hash.
    """
    if text.startswith("﻿"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _fail(detail: str, message: str, mark: Any = None) -> RestrictedYamlError:
    where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
    return RestrictedYamlError(f"{message}{where}", detail=detail)


class RestrictedYamlLoader(yaml.SafeLoader):
    """A ``SafeLoader`` narrowed to the supported rule document subset."""

    def compose_node(self, parent, index):  # type: ignore[no-untyped-def]
        event = self.peek_event()
        if isinstance(event, yaml.events.AliasEvent):
            raise _fail(
                "alias_not_supported",
                "YAML aliases are not supported in rule documents",
                event.start_mark,
            )
        if getattr(event, "anchor", None) is not None:
            raise _fail(
                "anchor_not_supported",
                "YAML anchors are not supported in rule documents",
                event.start_mark,
            )
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep: bool = False):  # type: ignore[no-untyped-def]
        if not isinstance(node, yaml.MappingNode):
            raise _fail("invalid_mapping", "expected a mapping", node.start_mark)
        mapping: dict[str, Any] = {}
        for key_node, value_node in node.value:
            if key_node.tag != "tag:yaml.org,2002:str":
                raise _fail(
                    "non_string_key",
                    "mapping keys must be strings",
                    key_node.start_mark,
                )
            key = self.construct_object(key_node, deep=deep)
            if key == "<<":
                raise _fail(
                    "merge_key_not_supported",
                    "YAML merge keys are not supported in rule documents",
                    key_node.start_mark,
                )
            if key in mapping:
                raise _fail(
                    "duplicate_key",
                    f"duplicate mapping key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping

    def construct_yaml_bool(self, node):  # type: ignore[no-untyped-def]
        value = self.construct_scalar(node)
        if value not in ("true", "false"):
            raise _fail(
                "ambiguous_boolean",
                f"ambiguous boolean scalar {value!r}; write true or false",
                node.start_mark,
            )
        return value == "true"

    def construct_yaml_int(self, node):  # type: ignore[no-untyped-def]
        value = self.construct_scalar(node)
        if not _INTEGER_RE.match(value):
            raise _fail(
                "ambiguous_integer",
                f"ambiguous integer scalar {value!r}; write a plain decimal integer",
                node.start_mark,
            )
        return int(value)

    def construct_yaml_float(self, node):  # type: ignore[no-untyped-def]
        value = self.construct_scalar(node)
        raise _fail(
            "float_not_supported",
            f"floating point values are not supported in rule documents ({value!r})",
            node.start_mark,
        )

    def construct_yaml_null(self, node):  # type: ignore[no-untyped-def]
        value = self.construct_scalar(node)
        if value != "null":
            raise _fail(
                "ambiguous_null",
                f"ambiguous null scalar {value!r}; write null explicitly",
                node.start_mark,
            )
        return None


RestrictedYamlLoader.yaml_constructors = dict(yaml.SafeLoader.yaml_constructors)
for _tag in _FORBIDDEN_TAGS:
    RestrictedYamlLoader.yaml_constructors.pop(_tag, None)
RestrictedYamlLoader.add_constructor(
    "tag:yaml.org,2002:bool", RestrictedYamlLoader.construct_yaml_bool
)
RestrictedYamlLoader.add_constructor(
    "tag:yaml.org,2002:int", RestrictedYamlLoader.construct_yaml_int
)
RestrictedYamlLoader.add_constructor(
    "tag:yaml.org,2002:float", RestrictedYamlLoader.construct_yaml_float
)
RestrictedYamlLoader.add_constructor(
    "tag:yaml.org,2002:null", RestrictedYamlLoader.construct_yaml_null
)


def load_restricted_yaml(text: str, *, source: str) -> Any:
    """Parse one restricted-YAML document and return plain Python data."""
    normalized = normalize_source(text)
    try:
        documents = list(yaml.load_all(normalized, Loader=RestrictedYamlLoader))
    except RestrictedYamlError:
        raise
    except yaml.YAMLError as exc:
        raise RestrictedYamlError(f"{source}: {exc}", detail="parse_error") from exc
    if len(documents) != 1:
        raise RestrictedYamlError(
            f"{source}: expected exactly one YAML document, found {len(documents)}",
            detail="multiple_documents",
        )
    document = documents[0]
    if not isinstance(document, dict):
        raise RestrictedYamlError(
            f"{source}: the document root must be a mapping",
            detail="invalid_root",
        )
    return document
