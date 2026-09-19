import Ajv2020, { type ErrorObject } from "ajv/dist/2020";

import caseSchema from "../../../../rules/schema/case.v1.schema.json";
import decisionSchema from "../../../../rules/schema/decision.v1.schema.json";
import evaluationRequestSchema from "../../../../rules/schema/evaluation-request.v1.schema.json";
import observationSchema from "../../../../rules/schema/observation.v1.schema.json";
import rulePackageSchema from "../../../../rules/schema/rule-package.v1.schema.json";
import ruleTemplatesSchema from "../../../../rules/schema/rule-templates.v1.schema.json";
import { ruleError, type RuleErrorCode } from "./errors";

const schemas = [
  caseSchema,
  decisionSchema,
  evaluationRequestSchema,
  observationSchema,
  rulePackageSchema,
  ruleTemplatesSchema,
] as const;

const ajv = new Ajv2020({ allErrors: true, strict: true, allowUnionTypes: true });
for (const schema of schemas) ajv.addSchema(schema);

export const schemaIds = {
  case: caseSchema.$id,
  decision: decisionSchema.$id,
  evaluationRequest: evaluationRequestSchema.$id,
  rulePackage: rulePackageSchema.$id,
  ruleTemplates: ruleTemplatesSchema.$id,
} as const;

export function validateSchema(
  schemaId: string,
  value: unknown,
  source: string,
  code: RuleErrorCode = "invalid_rule_package",
  detail = "schema_violation",
): void {
  const validate = ajv.getSchema(schemaId);
  if (!validate) ruleError("invalid_rule_package", "missing_schemas", `Missing schema ${schemaId}`);
  if (validate(value)) return;
  const first = stableErrors(validate.errors)[0];
  ruleError(
    code,
    detail,
    `${source}: schema violation at ${first?.instancePath || "/"}: ${first?.message ?? "invalid value"}`,
  );
}

function stableErrors(errors: ErrorObject[] | null | undefined): ErrorObject[] {
  return [...(errors ?? [])].sort((left, right) =>
    `${left.instancePath}:${left.keyword}:${left.message}`.localeCompare(
      `${right.instancePath}:${right.keyword}:${right.message}`,
    ),
  );
}
