/** The reactions page's rules on core's real `/api/reactions` of examples/process-ammonia. */
import { describe, expect, it } from "vitest";
import type { Reaction, ReactionsView, Sheet } from "@/api";
import {
  approachOf,
  arrheniusText,
  catalystOf,
  changeText,
  chartGeometry,
  elementBadge,
  equationText,
  equipmentSheets,
  extentOf,
  heatText,
  kineticsOf,
  lnText,
  nodePidLink,
  ordersText,
  rangeText,
  rateFormText,
} from "@/lib/reactions";
import reactionsJson from "./fixtures/api/reactions-ammonia.json";
import shiftJson from "./fixtures/api/reactions-shift.json";
import unbalancedJson from "./fixtures/api/reactions-ammonia-unbalanced.json";

const view = reactionsJson as unknown as ReactionsView;
const unbalanced = unbalancedJson as unknown as ReactionsView;
const syn = view.reactions[0]!;

describe("a reaction", () => {
  it("equation as written, else from the stoichiometry", () => {
    expect(equationText(syn)).toBe("N2 + 3 H2 <=> 2 NH3");
    expect(equationText({ ...syn, equation: "" })).toBe("N2 + 3 H2 <=> 2 NH3");
    expect(equationText({ equation: "", reversible: false, stoichiometry: { CH4: -1, O2: -2, CO2: 1, H2O: 2 } })).toBe("CH4 + 2 O2 -> CO2 + 2 H2O");
  });
  it("element balance badge", () => {
    expect(elementBadge(syn)).toMatchObject({ badge: "pass", label: "balanced" });
    const bad = elementBadge(unbalanced.reactions[0]!);
    expect(bad).toMatchObject({ badge: "error", label: "unbalanced" });
    expect(bad.title).toContain("N +1, H +3");
    expect(elementBadge({ element_balance: { evaluable: false, balanced: null, change: {} } }).label).toBe("not evaluable");
    expect(changeText({ C: -1, O: 2 })).toBe("C -1, O +2");
  });
  it("conversion, equilibrium constant, a unit's conversion, or ideal-gas data", () => {
    // NH3_SYN: an equilibrium reactor, no K given
    expect(extentOf(syn)).toEqual({ kind: "ideal-gas", text: "K from the components' ideal-gas data", provenance: null, source: "" });
    const conv: Reaction = { ...syn, type: "conversion", conversion: { key: "N2", value: 0.25, provenance: "assumed", source: "per pass" } };
    expect(extentOf(conv)).toEqual({ kind: "conversion", text: "X = 0.25 of N2", provenance: "assumed", source: "per pass" });
    const k: Reaction = { ...syn, equilibrium_constant: { a: -12.3, b: 6000, c: 0, d: 0, temperature_range: [600, 800], provenance: "given", source: "fit" } };
    expect(extentOf(k)).toMatchObject({ kind: "K", text: "ln K = -12.3 + 6000/T (600–800 K)", provenance: "given" });
    const kneg: Reaction = { ...syn, equilibrium_constant: { a: 1, b: -500, c: 0, d: 0, temperature_range: null, provenance: "assumed", source: "" } };
    expect(extentOf(kneg).text).toBe("ln K = 1 − 500/T");
    const inUnit: Reaction = { ...syn, type: "conversion", units: [{ ...syn.units[0]!, model: "conversion", conversion: { value: 0.3, from: "flowsheet R1" } }] };
    expect(extentOf(inUnit)).toEqual({ kind: "conversion", text: "X = 0.3 in R1", provenance: "given", source: "flowsheet R1" });
    expect(extentOf({ ...syn, type: null }).kind).toBeNull();
  });
  it("heat of reaction", () => {
    expect(heatText(syn.heat_of_reaction)).toBe("-91116 kJ/kmol at 298.15 K");
    expect(heatText(null)).toBe("");
  });
});

describe("a reactor", () => {
  it("how its outlet stands to equilibrium", () => {
    const r1 = view.reactors.find((r) => r.node === "R1")!;
    const lnqk = r1.reactions[0]!.ln_q_over_k;
    expect(approachOf(lnqk)).toEqual({ text: "at equilibrium", tone: "pass" });
    expect(lnText(lnqk)).toBe("-5.62e-6");
    expect(approachOf(-0.4)).toMatchObject({ tone: "warning" });
    expect(approachOf(0.4)).toMatchObject({ tone: "error" });
    expect(approachOf(null).text).toBe("");
    expect(lnText(-0.41234)).toBe("-0.4123");
    expect(lnText(null)).toBe("");
  });
  it("where its node is drawn: a link's sheet, the equipment list's, or none", () => {
    const sheets = [{ id: "P-01", file: "pid/P-01.xml", title: "Loop" }] as Sheet[];
    const link = (target: string, ref: string, sheet: string | null = null) => ({ target, ref, sheet, resolved: true, problem: null });
    const nodes = [
      { id: "R1", links: [link("equipment", "R-101", "P-01")] },
      { id: "R2", links: [link("equipment", "R-102")] },
      { id: "R3", links: [link("sheet", "P-01")] },
      { id: "R-104", links: [] },
      { id: "R5", links: [] },
    ];
    const tags = equipmentSheets({ equipment: [{ tag: "R-102", sheet: "P-01" }, { tag: "R-104", sheet: "pid/P-01.xml" }, { tag: "X" }] });
    expect(nodePidLink("R1", nodes, sheets)).toEqual({ file: "pid/P-01.xml", select: "R-101" });
    expect(nodePidLink("R2", nodes, sheets)).toBeNull();
    expect(nodePidLink("R2", nodes, sheets, tags)).toEqual({ file: "pid/P-01.xml", select: "R-102" });
    expect(nodePidLink("R3", nodes, sheets)).toEqual({ file: "pid/P-01.xml", select: null });
    expect(nodePidLink("R-104", nodes, sheets, tags)).toEqual({ file: "pid/P-01.xml", select: "R-104" });
    expect(nodePidLink("R5", nodes, sheets, tags)).toBeNull();
    expect(equipmentSheets(null).size).toBe(0);
    expect(equipmentSheets({ equipment: "x" }).size).toBe(0);
  });
});

describe("kinetics (core's real /api/reactions of examples/process-shift)", () => {
  const shift = shiftJson as unknown as ReactionsView;
  const wgs = shift.reactions[0]!;
  const catalysts = kineticsOf(shift).catalysts;
  it("a rate law's form, orders, Arrhenius parameters and range", () => {
    expect(rateFormText(wgs.rate!)).toBe("power law, per kg of catalyst, on partial pressures (bar)");
    expect(rateFormText({ form: "lhhw", basis: "volume", driving: "concentration" })).toBe("LHHW, per m³ of reactor, on concentrations (kmol/m³)");
    expect(ordersText(wgs.rate!.orders)).toBe("CO 1, CO2 -0.36, H2 -0.09");
    expect(arrheniusText(wgs.rate!.k, wgs.rate_law!.k_unit)).toBe("A 1000 kmol/(kg s) / bar^0.55, Ea 111000 kJ/kmol");
    expect(arrheniusText({ A: 2, Ea: 0, n: 1.5, T_ref: 300 })).toBe("A 2, Ea 0 kJ/kmol, n 1.5, T_ref 300 K");
    expect(rangeText(wgs.rate!.temperature_range, "K")).toBe("573.15–773.15 K");
    expect(rangeText(null, "K")).toBe("");
    expect(wgs.rate_law!.expression).toBe("r = k(T) · p_CO · p_CO2^-0.36 · p_H2^-0.09 · (1 - Q/K)");
  });
  it("the catalyst a reaction names, declared or not", () => {
    expect(catalystOf(wgs, catalysts)?.entry?.id).toBe("FE_CR");
    expect(catalystOf({ catalyst: "X", rate: null }, catalysts)).toEqual({ id: "X", entry: null });
    expect(catalystOf({ catalyst: "", rate: null }, catalysts)).toBeNull();
    expect(kineticsOf({ kinetics: null })).toEqual({ file: null, catalysts: [], findings: [] });
    expect(kineticsOf(view).catalysts[0]?.units[0]?.unit).toBe("R1");
  });
  it("a line chart of k(T) (log) and of a bed's temperature", () => {
    const k = chartGeometry(wgs.rate_law!.k_profile.map((p) => [p.temperature_K, p.k]), 200, 100, true)!;
    expect(k.log).toBe(true);
    expect(k.x).toEqual([573.15, 773.15]);
    expect(k.y[0]).toBeCloseTo(wgs.rate_law!.k_profile[0]!.k, 20);
    expect(k.d.startsWith("M0.0,100.0")).toBe(true);
    expect(k.d.endsWith("L200.0,0.0")).toBe(true);
    const bed = shift.reactors.find((r) => r.node === "R1")!.bed!;
    const t = chartGeometry(bed.profile.map((p) => [p.catalyst_mass_kg, p.temperature_K]), 200, 100)!;
    expect(t.log).toBe(false);
    expect(t.x[1]).toBe(bed.catalyst_mass_kg);
    expect(t.y[1]).toBeCloseTo(bed.hot_spot_K, 6);
    // flat: the line in the middle; too few points or no x range: none; log of a non-positive value: linear
    expect(chartGeometry([[0, 5], [1, 5]], 10, 10)!.d).toBe("M0.0,5.0 L10.0,5.0");
    expect(chartGeometry([[0, 1]], 10, 10)).toBeNull();
    expect(chartGeometry([[1, 1], [1, 2]], 10, 10)).toBeNull();
    expect(chartGeometry([[0, 0], [1, 2]], 10, 10, true)!.log).toBe(false);
  });
});
