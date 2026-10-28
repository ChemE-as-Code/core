/** The simulation view's rules on core's real `/api/simulation` (scripts/regen-fixtures.py). */
import { describe, expect, it } from "vitest";
import type { SimulationView } from "@/api";
import { filledFields, formatSimValue, resultEntries, runState, runTime, specEntries, unitConvergence } from "@/lib/simulation";
import asuJson from "./fixtures/api/simulation-asu.json";
import runJson from "./fixtures/api/simulation-run.json";
import staleJson from "./fixtures/api/simulation-stale.json";
import failedJson from "./fixtures/api/simulation-failed.json";

const asu = asuJson as unknown as SimulationView;
const current = runJson as unknown as SimulationView;
const stale = staleJson as unknown as SimulationView;
const failed = failedJson as unknown as SimulationView;

describe("runState", () => {
  it("not run, converged, not converged", () => {
    expect(runState(asu)).toBe("not-run");
    expect(runState(current)).toBe("converged");
    expect(runState(stale)).toBe("converged");
    expect(runState(failed)).toBe("failed");
  });
});

describe("unitConvergence", () => {
  it("from the run's row: converged, failed, unknown (not named), none without a run", () => {
    const of = (v: SimulationView, id: string) => unitConvergence(v.units.find((u) => u.id === id)?.run);
    expect(of(current, "K1")).toBe("converged");
    expect(of(failed, "E1")).toBe("failed");
    expect(of(failed, "K1")).toBe("unknown");
    expect(of(asu, "K1101")).toBeNull();
    expect(unitConvergence({ id: "K1", status: "excluded", reason: "x" })).toBeNull();
  });
});

describe("specEntries", () => {
  it("quantities with unit and provenance, plain values, nested maps by dotted key", () => {
    const k1101 = asu.units.find((u) => u.id === "K1101")!;
    const entries = specEntries(k1101.spec);
    expect(entries.find((e) => e.key === "pressure_drop")).toEqual({ key: "pressure_drop", text: "0.05 bar", provenance: "assumed", source: "per cooler" });
    expect(entries.find((e) => e.key === "stages")).toMatchObject({ text: "3", provenance: null });
    // a quantity without a unit: the flowsheet's
    expect(entries.find((e) => e.key === "outlet_pressure")?.text).toBe("5.8");
    const c3101 = specEntries(asu.units.find((u) => u.id === "C3101")!.spec);
    expect(c3101.find((e) => e.key === "side_draws.lin.flow")).toMatchObject({ text: "470", provenance: "assumed" });
    expect(c3101.find((e) => e.key === "side_draws.lin.phase")?.text).toBe("liquid");
    expect(c3101.find((e) => e.key === "condenser_spec.flow")?.text).toBe("24530");
    expect(c3101.find((e) => e.key === "outlets.n2")?.text).toBe("vapor");
    const split = specEntries(asu.units.find((u) => u.id === "X3102")!.spec);
    expect(split).toEqual([{ key: "split.bst", text: "0.1516", provenance: null, source: "" }]);
    expect(specEntries(null)).toEqual([]);
    expect(specEntries({ feed_stages: [1, 22] })[0]?.text).toBe("1, 22");
  });
});

describe("resultEntries", () => {
  it("splits the unit off the key", () => {
    expect(resultEntries(current.units[0]!.run!.results)).toEqual([{ key: "duty_kW", label: "duty", text: "84.2", unit: "kW" }]);
    expect(resultEntries({ outlet_temperature_K: 310.5, flow_kmol_h: 2, reflux_ratio: 1.2 })).toEqual([
      { key: "outlet_temperature_K", label: "outlet temperature", text: "310.5", unit: "K" },
      { key: "flow_kmol_h", label: "flow", text: "2", unit: "kmol/h" },
      { key: "reflux_ratio", label: "reflux ratio", text: "1.2", unit: "" },
    ]);
    expect(resultEntries(undefined)).toEqual([]);
  });
});

describe("filledFields", () => {
  it("the run's filled fields by stream, for the run's case only", () => {
    const filled = filledFields(current, "design");
    expect([...filled.keys()]).toEqual(["S2", "S3", "S4", "S5", "W1"]);
    expect([...filled.get("S2")!]).toEqual(["temperature", "pressure", "flow", "composition"]);
    expect([...filled.get("W1")!]).toEqual(["duty"]);
    expect(filledFields(current, "turndown").size).toBe(0);
    expect(filledFields(failed, "design").size).toBe(0); // no stream value written
    expect(filledFields(asu, "design").size).toBe(0);
    expect(filledFields(null, "design").size).toBe(0);
  });
});

describe("formatting", () => {
  it("values and the run time", () => {
    const s2 = current.run!.streams[0]!;
    expect(formatSimValue(s2.values.temperature)).toBe("598 K");
    expect(formatSimValue(s2.values.composition)).toBe("mol: N2 0.7812, O2 0.2096, AR 0.0092");
    expect(formatSimValue(undefined)).toBe("");
    expect(runTime("2026-10-23T12:57:30Z")).toBe("2026-10-23 12:57 UTC");
    expect(runTime("yesterday")).toBe("yesterday");
  });
});
