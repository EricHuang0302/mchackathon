import type { RuntimeStore } from "../offline/runtimeStore";
import { ruleError } from "./errors";
import { loadRulePackage } from "./package";
import type { RulePackage, RulePackageSources } from "./types";

type RuleStore = Pick<RuntimeStore, "loadRuleBundle" | "saveRuleBundle">;

export interface RuleReviewPolicy {
  allowUnreviewedDemo?: boolean;
}

interface StoredRuleSources {
  flowText: string;
  templatesText: string;
  flowSource: string;
  templatesSource: string;
  contentHash: string;
  reviewStatus: RulePackage["reviewStatus"];
  schemaVersion: "1.0.0";
}

export async function installRuleBundle(
  store: RuleStore,
  sources: RulePackageSources,
  policy: RuleReviewPolicy = {},
): Promise<RulePackage> {
  const normalizedSources = {
    ...sources,
    flowSource: sources.flowSource ?? "<flow>",
    templatesSource: sources.templatesSource ?? "<templates>",
  };
  const rulePackage = await loadRulePackage(normalizedSources);
  enforceReviewPolicy(rulePackage, policy);
  const existing = await store.loadRuleBundle(rulePackage.ruleVersion);
  if (existing) {
    const existingBundle = storedSources(existing.bundle);
    if (existingBundle.contentHash !== rulePackage.contentHash) {
      ruleError("rule_mismatch", "content_hash_mismatch", `Rule version ${rulePackage.ruleVersion} already has different content`);
    }
  }
  await store.saveRuleBundle({
    ruleVersion: rulePackage.ruleVersion,
    savedAt: new Date().toISOString(),
    bundle: {
      ...normalizedSources,
      contentHash: rulePackage.contentHash,
      reviewStatus: rulePackage.reviewStatus,
      schemaVersion: rulePackage.schemaVersion,
    } satisfies StoredRuleSources,
  });
  return rulePackage;
}

export async function loadRuleBundle(
  store: RuleStore,
  ruleVersion: string,
  policy: RuleReviewPolicy = {},
): Promise<RulePackage | undefined> {
  const record = await store.loadRuleBundle(ruleVersion);
  if (!record) return undefined;
  const cached = storedSources(record.bundle);
  const rulePackage = await loadRulePackage(cached);
  if (rulePackage.ruleVersion !== ruleVersion || rulePackage.contentHash !== cached.contentHash) {
    ruleError("rule_mismatch", "content_hash_mismatch", `Cached rule version ${ruleVersion} failed integrity validation`);
  }
  enforceReviewPolicy(rulePackage, policy);
  return rulePackage;
}

function enforceReviewPolicy(rulePackage: RulePackage, policy: RuleReviewPolicy): void {
  if (rulePackage.reviewStatus === "reviewed") return;
  if (rulePackage.reviewStatus === "unreviewed_demo" && policy.allowUnreviewedDemo) return;
  ruleError("invalid_rule_package", "review_not_approved", `Rule package ${rulePackage.ruleVersion} is not approved for this mode`);
}

function storedSources(value: unknown): StoredRuleSources {
  if (!isRecord(value) ||
    typeof value.flowText !== "string" ||
    typeof value.templatesText !== "string" ||
    typeof value.flowSource !== "string" ||
    typeof value.templatesSource !== "string" ||
    typeof value.contentHash !== "string" ||
    typeof value.reviewStatus !== "string" ||
    value.schemaVersion !== "1.0.0") {
    ruleError("invalid_rule_package", "invalid_cached_bundle", "Cached rule bundle is invalid");
  }
  return value as unknown as StoredRuleSources;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
