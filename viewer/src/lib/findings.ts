/**
 * Pure helpers for findings lists (validation, review needed).
 */
import type { Finding, Level } from "@/api";

/** True when `query` (trimmed, case-insensitive) occurs in the file, rule, message, hint or an id. */
export function matchesQuery(finding: Finding, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [finding.file, finding.rule, finding.message, finding.hint, ...finding.ids].some((s) =>
    s.toLowerCase().includes(q),
  );
}

/** Findings per level; unknown levels are not counted. */
export function countLevels(findings: Finding[]): Record<Level, number> {
  const out: Record<Level, number> = { error: 0, warning: 0, info: 0 };
  for (const f of findings) if (f.level in out) out[f.level]++;
  return out;
}

const LEVEL_RANK: Record<string, number> = { error: 0, warning: 1, info: 2 };

/** Findings of one rule, with their index in the full list (for click-to-highlight). */
export interface FindingGroup {
  rule: string;
  /** The most severe level among them. */
  level: Level;
  count: number;
  counts: Record<Level, number>;
  items: { finding: Finding; index: number }[];
}

/** Group findings by rule: most severe groups first, then the largest, then by rule name. */
export function groupFindings(findings: readonly Finding[]): FindingGroup[] {
  const groups = new Map<string, FindingGroup>();
  findings.forEach((finding, index) => {
    let g = groups.get(finding.rule);
    if (!g) {
      g = { rule: finding.rule, level: finding.level, count: 0, counts: { error: 0, warning: 0, info: 0 }, items: [] };
      groups.set(finding.rule, g);
    }
    g.items.push({ finding, index });
    g.count++;
    if (finding.level in g.counts) g.counts[finding.level]++;
    if ((LEVEL_RANK[finding.level] ?? 3) < (LEVEL_RANK[g.level] ?? 3)) g.level = finding.level;
  });
  return [...groups.values()].sort((a, b) => (LEVEL_RANK[a.level] ?? 3) - (LEVEL_RANK[b.level] ?? 3) || b.count - a.count || a.rule.localeCompare(b.rule));
}

/** Groups start open when the list is short. */
export const FINDINGS_OPEN_MAX = 10;
