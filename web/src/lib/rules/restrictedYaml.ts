import {
  isAlias,
  isMap,
  isScalar,
  isSeq,
  parseAllDocuments,
  type Node,
  type Pair,
} from "yaml";

import { RuleError, ruleError } from "./errors";

const DECIMAL_INTEGER = /^-?(0|[1-9][0-9]*)$/;
const AMBIGUOUS_BOOLEAN = /^(?:y|yes|n|no|true|false|on|off)$/i;
const AMBIGUOUS_INTEGER = /^(?:\+[0-9]+|-?0[xX][0-9a-fA-F]+|-?0[oO][0-7]+|-?0[bB][01]+|-?0[0-9]+|[-+]?[0-9][0-9_]*_[0-9_]*|[-+]?[0-9]+(?::[0-9]+)+)$/;
const FLOAT_LIKE = /^(?:[-+]?(?:[0-9]+\.[0-9]*|[0-9]*\.[0-9]+)(?:[eE][-+]?[0-9]+)?|[-+]?[0-9]+[eE][-+]?[0-9]+|[-+]?\.(?:inf|nan))$/i;
const DATE_LIKE = /^\d{4}-\d{2}-\d{2}(?:$|[Tt ])/;

export function normalizeSource(text: string): string {
  return text.replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n");
}

export function loadRestrictedYaml(text: string, source: string): Record<string, unknown> {
  const documents = parseAllDocuments(normalizeSource(text), {
    schema: "core",
    strict: true,
    uniqueKeys: true,
  });
  if (documents.length !== 1) {
    ruleError("restricted_yaml", "multiple_documents", `${source}: expected exactly one YAML document`);
  }
  const document = documents[0];
  if (!document) ruleError("restricted_yaml", "invalid_root", `${source}: missing YAML document`);
  if (document.errors.length > 0) {
    const message = document.errors[0]?.message ?? "invalid YAML";
    const detail = message.toLowerCase().includes("unique") ? "duplicate_key" : "parse_error";
    ruleError("restricted_yaml", detail, `${source}: ${message}`);
  }
  inspectNode(document.contents, source);
  if (!isMap(document.contents)) {
    ruleError("restricted_yaml", "invalid_root", `${source}: document root must be a mapping`);
  }
  try {
    return document.toJS({ maxAliasCount: 0 }) as Record<string, unknown>;
  } catch (error) {
    if (error instanceof RuleError) throw error;
    ruleError("restricted_yaml", "parse_error", `${source}: ${String(error)}`);
  }
}

function inspectNode(node: Node | null, source: string): void {
  if (!node) return;
  if (isAlias(node)) ruleError("restricted_yaml", "alias_not_supported", `${source}: aliases are not supported`);
  if ("anchor" in node && node.anchor) {
    ruleError("restricted_yaml", "anchor_not_supported", `${source}: anchors are not supported`);
  }
  if (isMap(node)) {
    for (const pair of node.items) inspectPair(pair, source);
    return;
  }
  if (isSeq(node)) {
    for (const child of node.items) inspectNode(child as Node | null, source);
    return;
  }
  if (!isScalar(node)) return;

  const raw = String(node.source ?? "");
  const plain = node.type === "PLAIN";
  const tag = node.tag;
  if (tag && !tag.startsWith("tag:yaml.org,2002:")) {
    ruleError("restricted_yaml", "parse_error", `${source}: custom YAML tags are not supported`);
  }
  if (typeof node.value === "number") {
    if (!Number.isInteger(node.value)) {
      ruleError("restricted_yaml", "float_not_supported", `${source}: floating point values are not supported`);
    }
    if (!DECIMAL_INTEGER.test(raw)) {
      ruleError("restricted_yaml", "ambiguous_integer", `${source}: ambiguous integer ${raw}`);
    }
  }
  if (typeof node.value === "boolean" && raw !== "true" && raw !== "false") {
    ruleError("restricted_yaml", "ambiguous_boolean", `${source}: ambiguous boolean ${raw}`);
  }
  if (node.value === null && raw !== "null") {
    ruleError("restricted_yaml", "ambiguous_null", `${source}: ambiguous null ${raw}`);
  }
  if (plain && typeof node.value === "string" && AMBIGUOUS_BOOLEAN.test(raw) && raw !== "true" && raw !== "false") {
    ruleError("restricted_yaml", "ambiguous_boolean", `${source}: ambiguous boolean ${raw}`);
  }
  if (plain && typeof node.value === "string" && AMBIGUOUS_INTEGER.test(raw)) {
    ruleError("restricted_yaml", "ambiguous_integer", `${source}: ambiguous integer ${raw}`);
  }
  if (plain && typeof node.value === "string" && FLOAT_LIKE.test(raw)) {
    ruleError("restricted_yaml", "float_not_supported", `${source}: floating point values are not supported`);
  }
  if (plain && typeof node.value === "string" && DATE_LIKE.test(raw)) {
    ruleError("restricted_yaml", "parse_error", `${source}: timestamps must be quoted strings`);
  }
}

function inspectPair(pair: Pair, source: string): void {
  if (!isScalar(pair.key) || typeof pair.key.value !== "string") {
    ruleError("restricted_yaml", "non_string_key", `${source}: mapping keys must be strings`);
  }
  if (pair.key.value === "<<") {
    ruleError("restricted_yaml", "merge_key_not_supported", `${source}: merge keys are not supported`);
  }
  inspectNode(pair.value as Node | null, source);
}
