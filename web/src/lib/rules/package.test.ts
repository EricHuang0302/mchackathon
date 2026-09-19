import { describe, expect, it } from "vitest";

import flowText from "../../../../rules/flows/demo-v1.flow.yaml?raw";
import templatesText from "../../../../rules/templates/demo-v1.zh-TW.templates.yaml?raw";
import type { RuleBundleRecord } from "../offline/runtimeStore";
import { installRuleBundle, loadRuleBundle } from "./cache";
import { RuleError } from "./errors";
import { loadRulePackage } from "./package";
import { loadRestrictedYaml, normalizeSource } from "./restrictedYaml";

const sources = {
  flowText,
  templatesText,
  flowSource: "demo-v1.flow.yaml",
  templatesSource: "demo-v1.zh-TW.templates.yaml",
};

class MemoryRuleStore {
  record?: RuleBundleRecord;

  async loadRuleBundle(ruleVersion: string) {
    return this.record?.ruleVersion === ruleVersion ? this.record : undefined;
  }

  async saveRuleBundle(record: RuleBundleRecord) {
    this.record = record;
  }
}

describe("rule package loading and caching", () => {
  it("loads the shared demo package with a stable normalized hash", async () => {
    const unix = await loadRulePackage(sources);
    const windows = await loadRulePackage({
      ...sources,
      flowText: `\uFEFF${normalizeSource(flowText).replaceAll("\n", "\r\n")}`,
      templatesText: normalizeSource(templatesText).replaceAll("\n", "\r\n"),
    });
    expect(unix.reviewStatus).toBe("unreviewed_demo");
    expect(windows.contentHash).toBe(unix.contentHash);
  });

  it.each([
    ["duplicate_key", "a: 1\na: 2\n"],
    ["anchor_not_supported", "a: &copy 1\n"],
    ["merge_key_not_supported", 'a:\n  "<<": {}\n'],
    ["float_not_supported", "a: 1.5\n"],
    ["ambiguous_integer", "a: +1\n"],
    ["ambiguous_boolean", "a: yes\n"],
    ["ambiguous_null", "a: ~\n"],
  ])("rejects restricted YAML: %s", (detail, yaml) => {
    expect(() => loadRestrictedYaml(yaml, "test.yaml")).toThrowError(
      expect.objectContaining({ code: "restricted_yaml", detail }),
    );
  });

  it("allows the demo package only under the explicit demo policy", async () => {
    const store = new MemoryRuleStore();
    await expect(installRuleBundle(store, sources)).rejects.toMatchObject({
      code: "invalid_rule_package",
      detail: "review_not_approved",
    } satisfies Partial<RuleError>);
    const installed = await installRuleBundle(store, sources, { allowUnreviewedDemo: true });
    expect(installed.ruleVersion).toBe("demo-v1");
    await expect(loadRuleBundle(store, "demo-v1")).rejects.toMatchObject({ detail: "review_not_approved" });
    await expect(loadRuleBundle(store, "demo-v1", { allowUnreviewedDemo: true })).resolves.toMatchObject({
      contentHash: installed.contentHash,
    });
  });

  it("refuses different content under an installed rule version", async () => {
    const store = new MemoryRuleStore();
    await installRuleBundle(store, sources, { allowUnreviewedDemo: true });
    const changed = {
      ...sources,
      templatesText: templatesText.replace("撥打 119 中", "正在撥打 119"),
    };
    await expect(installRuleBundle(store, changed, { allowUnreviewedDemo: true })).rejects.toMatchObject({
      code: "rule_mismatch",
      detail: "content_hash_mismatch",
    });
  });
});
