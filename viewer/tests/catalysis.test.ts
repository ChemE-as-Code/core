/** The catalysis results on core's real responses: a CO oxidation mechanism at its reactor's outlet, kinetic data with their fit, the library. */
import { describe, expect, it } from "vitest";
import type { KineticDataFile, KineticsView, LibraryEntry, LibraryView, Microkinetics, ReactionsView, ReactorRow } from "@/api";
import {
  addCommand,
  coverageBars,
  filterLibrary,
  fitRows,
  fugacityText,
  libraryMatch,
  masi,
  parameterName,
  parameterText,
  pressuresText,
  rateControlBars,
  rateDeterminingStep,
  rateUnit,
  sig,
  stepEquation,
  worstDeviation,
} from "@/lib/catalysis";
import cooxJson from "./fixtures/api/reactions-coox.json";
import ammoniaJson from "./fixtures/api/reactions-ammonia.json";
import shiftJson from "./fixtures/api/reactions-shift.json";
import kineticsJson from "./fixtures/api/kinetics-shift.json";
import libraryJson from "./fixtures/api/library-shift.json";

const coox = cooxJson as unknown as ReactionsView;
const kinetics = kineticsJson as unknown as KineticsView;
const library = libraryJson as unknown as LibraryView;
const mk = coox.reactions.find((r) => r.id === "COOX")!.microkinetics!;

/** Keys of *items* outside *known*: a field core serves that the viewer's types leave out. */
function unknownKeys(items: readonly object[], known: readonly string[]): string[] {
  return [...new Set(items.flatMap((i) => Object.keys(i)))].filter((k) => !known.includes(k)).sort();
}

describe("the contract of the catalysis responses", () => {
  it("microkinetics: the fields the type knows", () => {
    const known: (keyof Microkinetics)[] = [
      "conditions",
      "missing",
      "product",
      "tof_per_s",
      "coverages",
      "step_rates_per_s",
      "rate_control",
      "apparent_activation_kJ_kmol",
      "orders",
      "mechanism_source",
      "mechanism_provenance",
    ];
    // core repeats the conditions' reaction, T and pressures in the analysis: read from `conditions`
    expect(unknownKeys([mk], [...known, "reaction", "temperature_K", "pressures_bar"])).toEqual([]);
    expect(mk.conditions).toMatchObject({ unit: "R", stream: "S2", temperature_K: 500 });
    expect(coox.reactions.find((r) => r.id === "UNUSED")!.microkinetics).toEqual({ conditions: null, missing: "the reaction takes place in no block or step" });
  });
  it("the reactor rows say their gas model", () => {
    const rows = (ammoniaJson as unknown as ReactionsView).reactors;
    expect(rows.find((r) => r.node === "R1")!.fugacity).toBe("peng_robinson");
    expect((shiftJson as unknown as ReactionsView).reactors.every((r) => r.fugacity === "ideal")).toBe(true);
  });
  it("kinetic data files: data, fit and problem", () => {
    expect(unknownKeys([kinetics], ["rev", "directory", "files"])).toEqual([]);
    expect(unknownKeys(kinetics.files, ["file", "data", "fit", "problem"])).toEqual([]);
    const fitted = kinetics.files.filter((f) => f.fit);
    expect(unknownKeys(fitted.map((f) => f.fit!), ["rate", "parameters", "r_squared", "points", "residuals", "notes", "reverse"])).toEqual([]);
    expect(unknownKeys(fitted.flatMap((f) => Object.values(f.fit!.parameters)), ["value", "standard_error", "interval_95"])).toEqual([]);
    expect(unknownKeys(fitted.map((f) => f.data!), ["schema", "kind", "reaction", "catalyst", "basis", "points", "provenance", "source"])).toEqual([]);
  });
  it("library entries: the fields the type knows", () => {
    const known: (keyof LibraryEntry)[] = ["id", "title", "window", "components", "reactions", "catalysts", "model_basis", "sources"];
    expect(unknownKeys(library.entries, known)).toEqual([]);
    expect(unknownKeys(library.entries.flatMap((e) => e.components), ["id", "name", "cas", "formula", "in_plant"])).toEqual([]);
    expect(unknownKeys(library.entries.flatMap((e) => e.reactions), ["id", "equation", "reversible", "phase", "catalyst", "heat_of_reaction", "in_plant"])).toEqual([]);
    expect(unknownKeys(library.entries.flatMap((e) => e.catalysts), ["id", "name", "active_phase", "promoters", "support", "window", "poisons", "in_plant", "differs"])).toEqual([]);
  });
});

describe("a mechanism's steady state", () => {
  it("coverages, largest first, in percent", () => {
    const bars = coverageBars(mk.coverages);
    expect(bars[0]).toMatchObject({ id: "CO*", text: "100 %" });
    expect(bars.map((b) => b.id)).toEqual(["CO*", "*", "O*"]);
    expect(bars[2]!.text).toBe("7.19e-9");
    expect(bars.every((b) => b.width >= 0 && b.width <= 1)).toBe(true);
  });
  it("degree of rate control by size; the controlling step and the most abundant intermediate", () => {
    const bars = rateControlBars(mk.rate_control);
    expect(bars[0]).toMatchObject({ id: "S2", text: "1", width: 1 });
    expect(bars.slice(1).map((b) => b.text)).toEqual(["≈ 0", "≈ 0"]);
    expect(rateDeterminingStep(mk)).toBe("S2");
    expect(masi(mk)).toBe("CO*");
    expect(rateDeterminingStep({ rate_control: { S1: 0.4, S2: 0.6 } })).toBe("S2");
    expect(rateDeterminingStep({ rate_control: { S1: 0.5, S2: 0.5 } })).toBeNull();
    expect(rateControlBars({ S1: -1.4 })[0]).toMatchObject({ width: 1, text: "-1.4" });
    expect(masi({ coverages: { "*": 0.9, "A*": 0.1 } })).toBeNull();
  });
  it("numbers and conditions", () => {
    expect(sig(mk.tof_per_s)).toBe("7.718e-7");
    expect(sig(253078.5585)).toBe("253100");
    expect(sig(undefined)).toBe("");
    expect(pressuresText(mk.conditions!.pressures_bar)).toBe("CO 0.01005 bar, CO2 0.01005 bar, O2 0.09548 bar");
  });
  it("a step's equation from its stoichiometry", () => {
    const steps = coox.reactions.find((r) => r.id === "COOX")!.mechanism!.steps;
    expect(steps.map(stepEquation)).toEqual(["CO + * <=> CO*", "O2 + 2 * <=> 2 O*", "CO* + O* -> CO2 + 2 *"]);
    expect(stepEquation({ equation: "A + * = A*", stoichiometry: {} })).toBe("A + * = A*");
  });
  it("a reactor's gas model", () => {
    expect(fugacityText({ fugacity: "peng_robinson" })).toBe("Peng–Robinson");
    expect(fugacityText({ fugacity: "ideal" })).toBe("");
    expect(fugacityText({} as Pick<ReactorRow, "fugacity">)).toBe("");
  });
});

describe("kinetic data and their fit", () => {
  const wgs = kinetics.files.find((f) => f.file.endsWith("wgs.yaml"))!;
  it("the fit's parameters", () => {
    expect(wgs.fit!.reverse).toBe(true);
    expect(parameterName("ln_A")).toBe("ln A");
    expect(parameterName("order_CO")).toBe("order CO");
    expect(parameterText("Ea", { value: 111000, standard_error: 1200, interval_95: [108600, 113400] })).toBe("111000 kJ/kmol ± 1200 (95 %: 108600 to 113400)");
    expect(parameterText("order_CO", { value: 1, standard_error: null, interval_95: null })).toBe("1");
  });
  it("each point with the fit's rate; the worst deviation", () => {
    const rows = fitRows(wgs);
    expect(rows).toHaveLength(12);
    expect(rows[0]!.fitted! / rows[0]!.measured).toBeCloseTo(1, 10);
    expect(worstDeviation(rows)).toBeLessThan(1e-9);
    const off: Pick<KineticDataFile, "data" | "fit"> = { data: { ...wgs.data!, points: [wgs.data!.points[0]!] }, fit: { ...wgs.fit!, residuals: [Math.log(2)] } };
    expect(fitRows(off)[0]!.deviation).toBeCloseTo(-0.5, 12);
    expect(fitRows({ data: wgs.data, fit: null })[0]!.fitted).toBeNull();
    expect(worstDeviation(fitRows({ data: wgs.data, fit: null }))).toBeNull();
  });
  it("a file that does not validate", () => {
    const broken = kinetics.files.find((f) => f.file.endsWith("broken.yaml"))!;
    expect(broken.data).toBeNull();
    expect(broken.problem).toContain("broken.yaml");
    expect(fitRows(broken)).toEqual([]);
  });
  it("the unit of the rates", () => {
    expect(rateUnit("catalyst_mass")).toBe("kmol/(kg s)");
    expect(rateUnit("volume")).toBe("kmol/(m³ s)");
  });
});

describe("the reaction library", () => {
  const byId = new Map(library.entries.map((e) => [e.id, e]));
  it("what the plant has of an entry", () => {
    expect(library.entries).toHaveLength(23);
    expect(libraryMatch(byId.get("ht_shift")!)).toMatchObject({ state: "all", runs: true });
    expect(libraryMatch(byId.get("acrylonitrile")!)).toMatchObject({ state: "some", have: 1, runs: false }); // H2O only
    expect(library.entries.filter((e) => libraryMatch(e).runs).map((e) => e.id)).toEqual(["ht_shift", "lt_shift", "methanol", "steam_reforming"]); // each with WGS
    expect(libraryMatch({ components: [], reactions: [], catalysts: [] })).toEqual({ have: 0, of: 0, state: "none", runs: false });
    // the shift example's FE_CR has its own data: in the plant, but not the library's
    expect(byId.get("ht_shift")!.catalysts[0]).toMatchObject({ id: "FE_CR", in_plant: true, differs: true });
    const onlyCatalyst = { components: [], reactions: [], catalysts: [{ ...byId.get("ht_shift")!.catalysts[0]! }] };
    expect(libraryMatch(onlyCatalyst).runs).toBe(false);
    expect(libraryMatch({ ...onlyCatalyst, catalysts: [{ ...onlyCatalyst.catalysts[0]!, differs: false }] }).runs).toBe(true);
  });
  it("filters by process, component, CAS, equation or catalyst", () => {
    expect(filterLibrary(library.entries, "").length).toBe(23);
    expect(filterLibrary(library.entries, "ammox").map((e) => e.id)).toEqual(["acrylonitrile"]);
    expect(filterLibrary(library.entries, "7664-41-7").map((e) => e.id)).toContain("ammonia");
    expect(filterLibrary(library.entries, "bismuth").map((e) => e.id)).toContain("acrylonitrile");
    expect(filterLibrary(library.entries, "zzz")).toEqual([]);
  });
  it("the command that adds an entry", () => {
    expect(addCommand("ammonia")).toBe("cheme chemistry library ammonia --add");
  });
});
