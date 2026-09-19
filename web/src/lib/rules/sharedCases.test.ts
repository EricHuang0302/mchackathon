import { beforeAll, describe, expect, it } from "vitest";

import caseIndex from "../../../../rules/cases/index.json";
import flowText from "../../../../rules/flows/demo-v1.flow.yaml?raw";
import templatesText from "../../../../rules/templates/demo-v1.zh-TW.templates.yaml?raw";
import { RuleError } from "./errors";
import { RuleEvaluator } from "./evaluator";
import { loadRulePackage } from "./package";
import type { Decision } from "./types";

interface SharedCase {
  schemaVersion: string;
  caseId: string;
  ruleVersion: string;
  steps: Array<{
    stepId: string;
    request: unknown;
    expect?: Partial<Decision>;
    expectError?: { code: string };
  }>;
}

const modules = import.meta.glob<SharedCase>("../../../../rules/cases/*.case.json", {
  eager: true,
  import: "default",
});
const fileName = (path: string) => path.slice(path.lastIndexOf("/") + 1);
const cases = Object.entries(modules).map(([path, value]) => [fileName(path), value] as const);

describe("shared Python and TypeScript rule cases", () => {
  let evaluator: RuleEvaluator;

  beforeAll(async () => {
    evaluator = new RuleEvaluator(await loadRulePackage({
      flowText,
      templatesText,
      flowSource: "demo-v1.flow.yaml",
      templatesSource: "demo-v1.zh-TW.templates.yaml",
    }));
  });

  it("enumerates exactly the case files declared by the shared index", () => {
    expect(cases.map(([name]) => name).sort()).toEqual([...caseIndex.cases].sort());
  });

  for (const [name, sharedCase] of cases) {
    it(name, () => {
      expect(sharedCase.caseId).toBe(name.replace(/\.case\.json$/, ""));
      for (const step of sharedCase.steps) {
        if (step.expectError) {
          try {
            evaluator.evaluate(step.request);
            throw new Error(`${step.stepId} unexpectedly produced a decision`);
          } catch (error) {
            expect(error).toBeInstanceOf(RuleError);
            expect((error as RuleError).code).toBe(step.expectError.code);
          }
          continue;
        }
        const decision = evaluator.evaluate(step.request) as unknown as Record<string, unknown>;
        for (const [key, expected] of Object.entries(step.expect ?? {})) {
          expect(decision[key], `${sharedCase.caseId}/${step.stepId}/${key}`).toEqual(expected);
        }
      }
    });
  }
});
