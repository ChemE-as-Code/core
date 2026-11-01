/**
 * The control records of `GET /api/control` (core: `domains/control/report.py`): how a
 * review status and a finding count read, and which findings belong to which file.
 */
import type { ControlCounts, ControlFile, ControlStatus, Finding } from "@/api";

/** The badge class of a review status: accepted passes, reviewed is informational, drafted warns. */
export function statusTone(status: ControlStatus): "pass" | "info" | "warning" {
  if (status === "accepted") return "pass";
  if (status === "reviewed") return "info";
  return "warning";
}

/** `1 warning, 3 info`; "" when there are none. */
export function countsText(counts: ControlCounts): string {
  return (["error", "warning", "info"] as const)
    .filter((level) => counts[level] > 0)
    .map((level) => `${counts[level]} ${level}`)
    .join(", ");
}

/** The worst level among the counts, for a badge; null when there are none. */
export function worstLevel(counts: ControlCounts): "error" | "warning" | "info" | null {
  if (counts.error) return "error";
  if (counts.warning) return "warning";
  if (counts.info) return "info";
  return null;
}

/** The findings of one file, in the order core gives them. */
export function findingsOf(findings: readonly Finding[], file: string): Finding[] {
  return findings.filter((f) => f.file === file);
}

/** The status of the file at `path`, when the report lists it. */
export function fileStatus(files: readonly ControlFile[], path: string): ControlFile | undefined {
  return files.find((f) => f.path === path);
}

/** Labels of the file kinds. */
export const KIND_LABEL: Record<ControlFile["kind"], string> = {
  loops: "Loop register",
  sequences: "Sequences",
  interlocks: "Cause & effect",
  narrative: "Process narrative",
  philosophy: "Control philosophy",
};
