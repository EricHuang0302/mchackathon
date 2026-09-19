import demoFlow from "../../../../rules/flows/demo-v1.flow.yaml?raw";
import demoTemplates from "../../../../rules/templates/demo-v1.zh-TW.templates.yaml?raw";
import type { RuntimeStore } from "../offline/runtimeStore";
import { installRuleBundle, type RuleReviewPolicy } from "./cache";
import type { RulePackage } from "./types";

const bundledSources = {
  "demo-v1": {
    flowText: demoFlow,
    templatesText: demoTemplates,
    flowSource: "demo-v1.flow.yaml",
    templatesSource: "demo-v1.zh-TW.templates.yaml",
  },
} as const;

export async function installBundledRule(
  store: Pick<RuntimeStore, "loadRuleBundle" | "saveRuleBundle">,
  ruleVersion: string,
  policy: RuleReviewPolicy = {},
): Promise<RulePackage | undefined> {
  const sources = bundledSources[ruleVersion as keyof typeof bundledSources];
  return sources ? installRuleBundle(store, sources, policy) : undefined;
}
