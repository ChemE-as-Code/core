/**
 * The equipment estimate (`GET /api/estimate/equipment`, `cheme assess equipment`): each item's
 * status, the sums per status and the AACE accuracy range on a total. Core computes the costs;
 * this only groups and states them.
 */
import type { EquipmentCostLine, EquipmentEstimate } from "@/api";

/** What a line's status means: costed with installation, the equipment alone, the project's own, left out or no cost. */
export type CostStatus = "bare" | "purchased" | "own" | "excluded" | "uncovered";

/** The status of a line, from core's text (`bare module`, `purchased only`, `project cost`, `excluded: ...`, `not covered`). */
export function costStatus(line: Pick<EquipmentCostLine, "status">): CostStatus {
  const s = line.status.trim().toLowerCase();
  if (s === "bare module") return "bare";
  if (s === "purchased only") return "purchased";
  if (s === "project cost") return "own";
  if (s.startsWith("excluded")) return "excluded";
  return "uncovered";
}

/** Chip text and badge class per status, in the order the summary lists them. */
export const STATUS_CHIPS: Record<CostStatus, { label: string; badge: string; title: string }> = {
  bare: { label: "bare module", badge: "pass", title: "Purchased and bare module cost (installation and indirects included)" },
  purchased: { label: "purchased only", badge: "warning", title: "Purchased cost only: a pressure or material factor is missing, no bare module cost" },
  own: { label: "project cost", badge: "info", title: "The project's own cost (a quotation in estimate/cost-basis.yaml)" },
  excluded: { label: "excluded", badge: "na", title: "Left out of the estimate by the project, with a reason" },
  uncovered: { label: "not covered", badge: "error", title: "No cost: no correlation, no size, or a size outside the correlation's range" },
};
export const STATUS_ORDER: CostStatus[] = ["bare", "purchased", "own", "excluded", "uncovered"];

export interface StatusSum {
  status: CostStatus;
  count: number;
  /** Sum of the purchased costs of its lines. */
  purchased: number;
  /** Sum of the bare module costs of its lines. */
  bareModule: number;
}

/** Count and cost sums per status (only the statuses that occur, in {@link STATUS_ORDER}). */
export function statusSums(lines: readonly EquipmentCostLine[]): StatusSum[] {
  const out = new Map<CostStatus, StatusSum>();
  for (const line of lines) {
    const status = costStatus(line);
    const sum = out.get(status) ?? { status, count: 0, purchased: 0, bareModule: 0 };
    sum.count += 1;
    sum.purchased += line.purchased ?? 0;
    sum.bareModule += line.bare_module ?? 0;
    out.set(status, sum);
  }
  return STATUS_ORDER.flatMap((s) => {
    const sum = out.get(s);
    return sum ? [{ ...sum, purchased: Math.round(sum.purchased), bareModule: Math.round(sum.bareModule) }] : [];
  });
}

/**
 * The two percentages of an accuracy end as core writes it (`-20 % to -50 %`, `+30 % to +100 %`):
 * `[-20, -50]`; null when it does not read.
 */
export function parseAccuracy(text: string | null | undefined): [number, number] | null {
  const found = [...(text ?? "").replace(/−/g, "-").matchAll(/([-+]?)\s*(\d+(?:\.\d+)?)\s*%/g)].map((m) => Number(`${m[1] === "-" ? "-" : ""}${m[2]}`));
  if (found.length === 1) return [found[0]!, found[0]!];
  if (found.length !== 2 || found.some((v) => !Number.isFinite(v))) return null;
  return [found[0]!, found[1]!];
}

/**
 * The AACE range of a total: where its low end and its high end lie (each a range, as the class
 * gives it), e.g. class 5 on 1 000: low end 500 to 800, high end 1 300 to 2 000. Null when the
 * accuracy does not read.
 */
export function accuracyBand(total: number, accuracy: EquipmentEstimate["accuracy"] | null | undefined): { low: [number, number]; high: [number, number] } | null {
  const low = parseAccuracy(accuracy?.low);
  const high = parseAccuracy(accuracy?.high);
  if (!low || !high) return null;
  const at = (pct: number) => Math.round(total * (1 + pct / 100));
  const sorted = (a: number, b: number): [number, number] => (a <= b ? [a, b] : [b, a]);
  return { low: sorted(at(low[0]), at(low[1])), high: sorted(at(high[0]), at(high[1])) };
}

/** Whether a line matches a filter text (each word in its tag, type, correlation, status, size source or notes). */
export function costLineMatches(line: EquipmentCostLine, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const text = [line.tag, line.type, line.correlation ?? "", line.status, line.size_source, line.notes].join(" ").toLowerCase();
  return words.every((w) => text.includes(w));
}

/** Whole currency units with thousands separators (`4,002,556`), empty for none. */
export function wholeMoney(value: number | null | undefined, currency = ""): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "";
  const text = Math.round(value).toLocaleString("en");
  return currency ? `${text} ${currency}` : text;
}

/** Whether a size source is an assumption (`ASSUMED`) or a draft datasheet's value. */
export function sizeAssumed(source: string): boolean {
  return /\bASSUMED\b/.test(source) || source.startsWith("draft ");
}
