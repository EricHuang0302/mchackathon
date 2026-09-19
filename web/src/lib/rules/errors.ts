export type RuleErrorCode =
  | "invalid_rule_package"
  | "restricted_yaml"
  | "rule_mismatch"
  | "stale_revision"
  | "invalid_input";

export class RuleError extends Error {
  constructor(
    readonly code: RuleErrorCode,
    message: string,
    readonly detail?: string,
  ) {
    super(message);
    this.name = "RuleError";
  }
}

export function ruleError(
  code: RuleErrorCode,
  detail: string,
  message: string,
): never {
  throw new RuleError(code, message, detail);
}
