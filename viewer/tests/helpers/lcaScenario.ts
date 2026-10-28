/** The part of an LcaReport (src/api.ts) the helper reads; structural, so the e2e build needs no app types. */
interface Impact {
  category: string;
  key: string;
  factor: number;
  value: number;
  scenario: string;
}
interface Gap {
  scenario: string;
}
interface Report {
  impacts: Impact[];
  gaps?: Gap[];
  scenarios: Record<string, Record<string, number>>;
  scenario_ids?: string[];
}

/** The scenario id the helper adds: synthetic, for tests of the scenario views only. */
export const LOW_GRID = "low-grid";

/**
 * *report* with a synthetic scenario `low-grid`: the baseline with every `feed:POWER` contribution
 * scaled by *factor*. The ASU's real LCA has no scenario (process-library D-091: no published open
 * grid projection yet), so the views that compare scenarios are tested on this one.
 */
export function withLowGrid<T extends Report>(
  report: T,
  factor = 0.25,
): T {
  const added = report.impacts
    .filter((i) => i.scenario === "baseline")
    .map((i) => (i.key === "feed:POWER" ? { ...i, scenario: LOW_GRID, factor: i.factor * factor, value: i.value * factor } : { ...i, scenario: LOW_GRID }));
  const totals: Record<string, number> = {};
  for (const i of added) totals[i.category] = (totals[i.category] ?? 0) + i.value;
  // core writes the gaps once per scenario: the same exchanges lack a burden in low-grid
  const gaps = report.gaps?.filter((g) => g.scenario === "baseline").map((g) => ({ ...g, scenario: LOW_GRID }));
  return {
    ...report,
    impacts: [...report.impacts, ...added],
    ...(report.gaps ? { gaps: [...report.gaps, ...(gaps ?? [])] } : {}),
    scenarios: { ...report.scenarios, [LOW_GRID]: totals },
    scenario_ids: [...(report.scenario_ids ?? ["baseline"]), LOW_GRID],
  };
}

/** The scenario id of {@link withMissingGrid}: synthetic, regional, without a grid factor. */
export const NO_GRID = "de-grid";

/**
 * *report* with a synthetic regional scenario `de-grid` (pre-release issue 172) whose electricity is declared
 * missing: the baseline without its `feed:POWER` contributions, which become gaps. Its total is the
 * rest, so a page must not compare it with the baseline as a lower footprint.
 */
export function withMissingGrid<T extends Report>(report: T): T {
  const kept = report.impacts.filter((i) => i.scenario === "baseline" && i.key !== "feed:POWER").map((i) => ({ ...i, scenario: NO_GRID }));
  const totals: Record<string, number> = {};
  for (const i of kept) totals[i.category] = (totals[i.category] ?? 0) + i.value;
  const power = report.impacts.filter((i) => i.scenario === "baseline" && i.key === "feed:POWER");
  const gaps = [
    ...(report.gaps?.filter((g) => g.scenario === "baseline").map((g) => ({ ...g, scenario: NO_GRID })) ?? []),
    ...power.map((i) => ({ category: i.category, key: i.key, reason: "missing", quantity: 1, unit: "kWh", phase: "operation", scenario: NO_GRID, detail: "no DE grid factor" })),
  ];
  return {
    ...report,
    impacts: [...report.impacts, ...kept],
    gaps: [...(report.gaps ?? []), ...gaps],
    scenarios: { ...report.scenarios, [NO_GRID]: totals },
    scenario_ids: [...(report.scenario_ids ?? ["baseline"]), NO_GRID],
    scenario_details: [{ id: NO_GRID, title: "Germany grid", location: "DE", year: 2026, electricity: "grid-average", case: null, source: "synthetic" }],
  };
}
