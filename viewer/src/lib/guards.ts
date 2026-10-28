/** Type guards for data whose shape is only known at run time (YAML documents, files read as text). */

/** A mapping (a JSON or YAML object): not null and not a list. */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
