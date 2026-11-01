/**
 * The fixed beds on core's real answers: `/api/reactions` of the shift example with
 * R1 adiabatic (the outlet hottest), cooled (an interior hot spot, the catalyst window below
 * it), cooled harder (the inlet hottest), isothermal and not solvable; the ammonia example (an
 * equilibrium reactor, no bed); a coupled kinetic bed with its recorded run current, stale and
 * not converged (`/api/simulation`).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, defineComponent, h, nextTick } from "vue";
import { RouterView, createMemoryHistory, createRouter } from "vue-router";
import { api, ApiError, type ReactionsView, type ReactorBed, type SimulationView } from "@/api";
import BedProfile from "@/components/BedProfile.vue";
import ReactionsPage from "@/views/ReactionsView.vue";
import { bedMode, bedRunRecord, chartScale, declaredBed, fixedBeds, isConstant, nearestIndex, peakPlace, profileCsv, temperatureReferences, type BedEntry } from "@/lib/fixedBed";
import ammoniaJson from "./fixtures/api/reactions-ammonia.json";
import shiftJson from "./fixtures/api/reactions-shift.json";
import cooledJson from "./fixtures/api/reactions-bed-cooled.json";
import inletJson from "./fixtures/api/reactions-bed-inlet.json";
import isothermalJson from "./fixtures/api/reactions-bed-isothermal.json";
import failedJson from "./fixtures/api/reactions-bed-failed.json";
import simJson from "./fixtures/api/reactions-bed-sim.json";
import runJson from "./fixtures/api/simulation-bed-run.json";
import staleJson from "./fixtures/api/simulation-bed-stale.json";
import runFailedJson from "./fixtures/api/simulation-bed-failed.json";
import otherRunJson from "./fixtures/api/simulation-run.json";

const ammonia = ammoniaJson as unknown as ReactionsView;
const shift = shiftJson as unknown as ReactionsView;
const cooled = cooledJson as unknown as ReactionsView;
const inlet = inletJson as unknown as ReactionsView;
const isothermal = isothermalJson as unknown as ReactionsView;
const failed = failedJson as unknown as ReactionsView;
const sim = simJson as unknown as ReactionsView;
const run = runJson as unknown as SimulationView;
const stale = staleJson as unknown as SimulationView;
const runFailed = runFailedJson as unknown as SimulationView;

const bedOf = (view: ReactionsView) => fixedBeds(view.reactors)[0]!;

describe("which reactors have a bed", () => {
  it("none in a process whose reactor is no fixed bed, and none from a core before beds", () => {
    expect(ammonia.reactors.length).toBeGreaterThan(0);
    expect(fixedBeds(ammonia.reactors)).toEqual([]);
    const { bed: _bed, ...older } = shift.reactors.find((r) => r.node === "R1")!;
    expect(fixedBeds([older as never])).toEqual([]);
  });
  it("a solved bed, and a bed core could not solve with core's reason", () => {
    expect(fixedBeds(shift.reactors).map((b) => b.node)).toEqual(["R1"]);
    const entry = bedOf(failed);
    expect(entry.bed).toBeNull();
    expect(entry.failure).toEqual(["a cooled bed needs coolant_temperature, heat_transfer_coefficient and diameter"]);
  });
});

describe("the declared bed and its reference temperatures", () => {
  it("the mode, the coolant and the catalyst window, each with its basis and provenance", () => {
    const declared = declaredBed("R1", cooled.kinetics);
    expect(bedMode(declared)).toBe("cooled");
    const refs = temperatureReferences(declared);
    expect(refs.map((r) => [r.kind, r.value_K])).toEqual([
      ["coolant", 620],
      ["catalyst-max", 640],
      ["catalyst-min", 583.15],
    ]);
    expect(refs[0]!.basis).toMatch(/boundary condition.*not a limit/);
    expect(refs[1]!.basis).toMatch(/guidance of catalyst FE_CR.*not an engineering maximum allowable temperature/);
    expect(refs[1]).toMatchObject({ provenance: "assumed", source: "310-500 C (Twigg, Catalyst Handbook)" });
  });
  it("no coolant for an adiabatic bed; nothing without kinetics (an older server)", () => {
    expect(temperatureReferences(declaredBed("R1", shift.kinetics)).map((r) => r.kind)).toEqual(["catalyst-max", "catalyst-min"]);
    expect(bedMode(declaredBed("R1", null))).toBeNull();
    expect(temperatureReferences(null)).toEqual([]);
    expect(declaredBed("SHIFT", shift.kinetics)).toBeNull();
  });
});

describe("where core's peak is", () => {
  it("at the outlet of the adiabatic bed (monotonic)", () => {
    const bed = bedOf(shift).bed!;
    expect(bed.hot_spot_K).toBe(bed.outlet_temperature_K);
    expect(peakPlace(bed)).toEqual({ uniform: false, inlet: false, outlet: true, interior: [], between: false });
  });
  it("inside the cooled bed, at the sampled point core's peak is", () => {
    const bed = bedOf(cooled).bed!;
    const place = peakPlace(bed)!;
    expect(place.interior).toEqual([12800]);
    expect(bed.profile.find((p) => p.catalyst_mass_kg === 12800)!.temperature_K).toBe(bed.hot_spot_K);
    expect(bed.hot_spot_K).toBeGreaterThan(bed.outlet_temperature_K);
    expect(bed.hot_spot_K).toBeGreaterThan(bed.profile[0]!.temperature_K);
  });
  it("at the inlet of a bed cooled harder", () => {
    expect(peakPlace(bedOf(inlet).bed!)).toMatchObject({ inlet: true, outlet: false, interior: [], between: false });
  });
  it("everywhere in the isothermal bed", () => {
    const bed = bedOf(isothermal).bed!;
    expect(peakPlace(bed)!.uniform).toBe(true);
    expect(isConstant(bed, "temperature_K")).toBe(true);
    expect(isConstant(bed, "pressure_kPa")).toBe(false);
  });
  it("between sampled points when core's peak is none of them (never the nearest point)", () => {
    const bed = bedOf(cooled).bed!;
    const narrow: ReactorBed = { ...bed, hot_spot_K: bed.hot_spot_K + 0.5 };
    expect(peakPlace(narrow)).toEqual({ uniform: false, inlet: false, outlet: false, interior: [], between: true });
    expect(peakPlace({ ...bed, profile: [] })).toBeNull();
  });
  it("a bed without pressure drop has a constant pressure", () => {
    const bed = bedOf(sim).bed!;
    expect(bed.notes[0]).toMatch(/^no pressure drop/);
    expect(isConstant(bed, "pressure_kPa")).toBe(true);
  });
});

describe("the profile as data", () => {
  it("CSV with every value as core gives it", () => {
    const bed = bedOf(cooled).bed!;
    const lines = profileCsv(bed).trimEnd().split("\n");
    expect(lines[0]).toBe("catalyst_mass_kg,temperature_K,pressure_kPa");
    expect(lines).toHaveLength(bed.profile.length + 1);
    expect(lines[17]).toBe(`12800,${bed.hot_spot_K},${bed.profile[16]!.pressure_kPa}`);
  });
  it("the chart spans the profile and the reference lines; the crosshair picks the nearest point", () => {
    const bed = bedOf(cooled).bed!;
    const points = bed.profile.map((p) => [p.catalyst_mass_kg, p.temperature_K] as [number, number]);
    const scale = chartScale(points, [583.15, 640, 620], 400, 100)!;
    expect(scale.x).toEqual([0, 40000]);
    expect(scale.y[0]).toBeLessThan(583.15);
    expect(scale.y[1]).toBeGreaterThan(bed.hot_spot_K);
    expect(scale.py(scale.y[1])).toBeCloseTo(0, 9);
    expect(scale.px(40000)).toBe(400);
    expect(scale.yTicks.every((t) => t >= scale.y[0] && t <= scale.y[1])).toBe(true);
    expect(scale.yTicks.length).toBeGreaterThanOrEqual(3);
    expect(nearestIndex(points, 12900)).toBe(16);
    expect(chartScale([[0, 1]], [], 10, 10)).toBeNull();
  });
});

describe("the bed's row of a recorded simulation run", () => {
  it("current, with the peak and pressure drop core recorded", () => {
    const record = bedRunRecord(run, "R1")!;
    expect(record).toMatchObject({ state: "current", hot_spot_K: bedOf(sim).bed!.hot_spot_K, pressure_drop_kPa: 0, changed: [] });
    expect(record.tool).toMatch(/^cheme-as-code /);
    expect(record.loop).toMatchObject({ converged: true, iterations: 1 });
  });
  it("stale after the bed changed: its values historical, the changed files named", () => {
    expect(bedRunRecord(stale, "R1")).toMatchObject({ state: "stale", changed: ["process/flowsheet.yaml"] });
  });
  it("not converged: no peak recorded, the outer loop's iterations", () => {
    const record = bedRunRecord(runFailed, "R1")!;
    expect(record).toMatchObject({ state: "failed", hot_spot_K: null, loop: { converged: false, iterations: 3, max_iterations: 3 } });
  });
  it("staleness core cannot tell is unknown; a failed run that is also stale says both; messages once", () => {
    expect(bedRunRecord({ ...run, stale: null }, "R1")!.state).toBe("unknown");
    expect(bedRunRecord({ ...runFailed, stale: true, staleness: { ...runFailed.staleness, changed_files: ["process/flowsheet.yaml"] } }, "R1")).toMatchObject({ state: "failed", stale: true });
    const doubled = structuredClone(runFailed);
    doubled.run!.messages = ["R1: no rate law"];
    doubled.run!.units.find((u) => u.id === "R1")!.messages = ["R1: no rate law"];
    expect(bedRunRecord(doubled, "R1")!.messages).toEqual(["R1: no rate law"]);
  });
  it("none without a run, for another unit, or for a unit that is no bed", () => {
    expect(bedRunRecord(null, "R1")).toBeNull();
    expect(bedRunRecord({ ...run, run: null }, "R1")).toBeNull();
    expect(bedRunRecord(run, "R2")).toBeNull();
    expect(bedRunRecord(otherRunJson as unknown as SimulationView, "K1")).toBeNull();
  });
});

function router(page: ReturnType<typeof defineComponent>) {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/reactions", name: "reactions", component: page },
      { path: "/pid/:path(.*)*", name: "pid", component: { render: () => null } },
      { path: "/file/:path(.*)*", name: "file", component: { render: () => null } },
      { path: "/streams", name: "streams", component: { render: () => null } },
      { path: "/library", name: "library", component: { render: () => null } },
    ],
  });
}

async function mountWith(page: ReturnType<typeof defineComponent>) {
  const el = document.createElement("div");
  document.body.appendChild(el);
  const r = router(page);
  const app = createApp({ render: () => h(RouterView) });
  app.use(r);
  await r.push("/reactions");
  await r.isReady();
  app.mount(el);
  for (let i = 0; i < 5; i++) await nextTick();
  await new Promise((resolve) => setTimeout(resolve, 0));
  await nextTick();
  return { el, unmount: () => (app.unmount(), el.remove()) };
}

function card(view: ReactionsView, record: SimulationView | null = null, snapshotTool: string | null = null) {
  const entry: BedEntry = bedOf(view);
  return mountWith(
    defineComponent(() => () =>
      h(BedProfile, {
        entry,
        declared: declaredBed(entry.node, view.kinetics),
        run: bedRunRecord(record, entry.node),
        caseId: view.case,
        source: "commit abc1234",
        snapshotTool,
        pid: null,
        csvName: "bed.csv",
      }),
    ),
  );
}

describe("BedProfile", () => {
  it("the shift example: endpoint values, both profiles, the peak at the outlet, no judgement", async () => {
    const { el, unmount } = await card(shift);
    const bed = bedOf(shift).bed!;
    expect(el.querySelector("[data-bed-mode]")?.textContent).toBe("adiabatic");
    expect(el.querySelector("[data-bed-inlet]")?.textContent).toBe("623.15 K, 3000 kPa");
    expect(el.querySelector("[data-bed-outlet]")?.textContent).toBe("704.415 K, 2999.25 kPa");
    expect(el.querySelector("[data-bed-rise]")?.textContent).toMatch(/^\+81\.2652 K/);
    expect(el.querySelector("[data-pressure-drop]")?.textContent).toBe("0.7491 kPa");
    expect(el.querySelector("[data-bed-catalyst]")?.textContent).toMatch(/^40000 kg, 35\.4 m³ of bed \(FE_CR\)/);
    expect(el.querySelector("[data-hot-spot] strong")?.textContent).toBe("704.415 K");
    expect(el.querySelector("[data-peak-place]")?.textContent).toBe("the sampled value at the outlet (40000 kg): an endpoint maximum, no interior hot spot");
    expect(el.querySelector("[data-bed-limit]")?.textContent).toMatch(/without a safe or unsafe judgement/);
    expect(el.querySelector("[data-bed-resolution]")?.textContent).toMatch(/51 sampled points over 40000 kg/);
    expect(el.querySelector("[data-refine]")).toBeNull();
    const charts = el.querySelectorAll("[data-bed-chart]");
    expect(charts).toHaveLength(2);
    expect(charts[0]!.querySelector("[data-x-max]")?.textContent).toBe("40000 (outlet)");
    expect(charts[0]!.textContent).toContain("catalyst mass from the inlet (kg)");
    expect(charts[0]!.textContent).not.toMatch(/length|axial position/i);
    expect(charts[0]!.querySelectorAll("[data-peak-marker]")).toHaveLength(1);
    expect(charts[1]!.querySelector("[data-peak-marker]")).toBeNull();
    expect(charts[0]!.querySelector('[data-legend="catalyst-max"]')?.textContent).toMatch(/Catalyst window 583\.15–773\.15 K/);
    expect(el.querySelector("[data-bed-source]")?.textContent).toMatch(/Solved by core from the inputs of commit abc1234.*case design.*no input fingerprint or model version/s);
    expect(el.querySelectorAll(".profile-table tbody tr")).toHaveLength(bed.profile.length);
    expect(el.textContent).not.toMatch(/\bsafe\b(?! or unsafe)/);
    unmount();
  });

  it("the cooled bed: the interior peak marked where core has it, the coolant and the window as references", async () => {
    const { el, unmount } = await card(cooled);
    expect(el.querySelector("[data-bed-mode-text]")?.textContent).toBe("cooled: coolant 620 K, U 30 W/(m² K), 800 tubes of 0.1 m");
    expect(el.querySelector("[data-peak-place]")?.textContent).toBe("the sampled value at 12800 kg (inside the bed): an interior hot spot");
    const chart = el.querySelector("[data-bed-chart]")!;
    expect([...chart.querySelectorAll("[data-reference]")].map((l) => l.getAttribute("data-reference"))).toEqual(["coolant", "catalyst-max"]);
    expect(chart.querySelector('[data-legend="coolant"]')?.textContent).toMatch(/Coolant 620 K: the cooled bed's boundary condition .* not a limit \(assumed/);
    expect(chart.querySelector('[data-legend="catalyst-max"]')?.textContent).toMatch(/Catalyst window 583\.15–640 K: operating-range guidance/);
    expect(chart.querySelector("[data-peak-line]")).toBeNull();
    expect(chart.querySelector('[data-legend="catalyst-max"] [data-outside]')).not.toBeNull();
    unmount();
  });

  it("a reference outside the profile's range is listed, not drawn", async () => {
    const { el, unmount } = await card(shift);
    const chart = el.querySelector("[data-bed-chart]")!;
    expect([...chart.querySelectorAll("[data-reference]")].map((l) => l.getAttribute("data-reference"))).toEqual([]);
    expect(chart.querySelector('[data-legend="catalyst-max"] [data-outside]')).not.toBeNull();
    unmount();
  });

  it("the crosshair reads out each sampled point from the keyboard", async () => {
    const { el, unmount } = await card(cooled);
    const svg = el.querySelector("[data-bed-chart] svg")!;
    svg.dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true }));
    await nextTick();
    expect(el.querySelector("[data-readout]")?.textContent).toMatch(/^Catalyst mass 40000 kg \(outlet\): T 627\.45 K/);
    svg.dispatchEvent(new KeyboardEvent("keydown", { key: "Home", bubbles: true }));
    await nextTick();
    expect(el.querySelector("[data-readout]")?.textContent).toBe("Catalyst mass 0 kg (inlet): T 623.15 K");
    unmount();
  });

  it("a peak between sampled points: a line at its value, no position, a refinement warning", async () => {
    const view = structuredClone(cooled);
    view.reactors.find((r) => r.node === "R1")!.bed!.hot_spot_K += 0.5;
    const { el, unmount } = await card(view);
    expect(el.querySelector("[data-peak-place]")?.textContent).toMatch(/no sampled point has this value: an interior hot spot between two of them; core reports its value, not its catalyst mass/);
    expect(el.querySelector("[data-refine]")).not.toBeNull();
    expect(el.querySelector("[data-peak-line]")).not.toBeNull();
    expect(el.querySelector("[data-peak-marker]")).toBeNull();
    unmount();
  });

  it("the isothermal bed: no temperature chart, the pressure profile only", async () => {
    const { el, unmount } = await card(isothermal);
    expect(el.querySelector('[data-flat="temperature"]')?.textContent).toMatch(/623\.15 K at every sampled point \(isothermal bed\)/);
    expect(el.querySelectorAll("[data-bed-chart]")).toHaveLength(1);
    expect(el.querySelector("[data-bed-chart]")?.getAttribute("aria-label")).toMatch(/^Pressure/);
    unmount();
  });

  it("a bed without pressure drop: no pressure chart, core's note; the run record and the snapshot it is from", async () => {
    const { el, unmount } = await card(sim, run, "cheme-as-code 0.9.0");
    expect(el.querySelector('[data-flat="pressure"]')?.textContent).toMatch(/no pressure profile to draw \(core calculated no pressure drop, see its notes\)/);
    expect(el.querySelector("[data-bed-notes]")?.textContent).toMatch(/no pressure drop: the catalyst's particle_diameter or bed_voidage is not given/);
    expect(el.querySelector("[data-bed-mode]")?.textContent).toBe("adiabatic");
    expect(el.querySelector("[data-run-state]")?.textContent).toBe("current");
    expect(el.querySelector("[data-run-values]")?.textContent).toMatch(/peak 728\.022 K, pressure drop 0 kPa/);
    expect(el.querySelector("[data-bed-source]")?.textContent).toMatch(/static snapshot of commit abc1234 written by cheme-as-code 0\.9\.0/);
    unmount();
  });

  it("a stale run's values are historical; a failed run records none", async () => {
    let mounted = await card(sim, stale);
    expect(mounted.el.querySelector("[data-run-state]")?.textContent).toBe("stale");
    expect(mounted.el.querySelector("[data-run-values]")?.textContent).toMatch(/^\s*Historical: peak 728\.022 K/);
    expect(mounted.el.querySelector("[data-run-stale]")?.textContent).toMatch(/process\/flowsheet\.yaml/);
    mounted.unmount();
    mounted = await card(sim, runFailed);
    expect(mounted.el.querySelector("[data-run-state]")?.textContent).toBe("not converged");
    expect(mounted.el.querySelector("[data-run-values]")).toBeNull();
    expect(mounted.el.querySelector("[data-run-failed]")?.textContent).toMatch(/stopped after 3 of 3 DWSIM solves; no converged bed result \(core keeps only the last, unconverged iterate\)/);
    mounted.unmount();
  });

  it("a bed core could not solve: its reason, no chart, no values", async () => {
    const { el, unmount } = await card(failed);
    expect(el.querySelector("[data-bed-state]")?.getAttribute("data-bed-state")).toBe("failed");
    expect(el.querySelector("[data-bed-failure]")?.textContent).toMatch(/a cooled bed needs coolant_temperature, heat_transfer_coefficient and diameter/);
    expect(el.querySelector("[data-bed-chart]")).toBeNull();
    expect(el.querySelector("[data-hot-spot]")).toBeNull();
    unmount();
  });
});

describe("the reactions page", () => {
  afterEach(() => vi.restoreAllMocks());

  async function page(view: ReactionsView, record: SimulationView | null = null) {
    vi.spyOn(api, "reactions").mockResolvedValue(view);
    vi.spyOn(api, "streams").mockRejectedValue(new Error("none"));
    vi.spyOn(api, "yaml").mockRejectedValue(new Error("none"));
    vi.spyOn(api, "kinetics").mockRejectedValue(new Error("none"));
    const simulation = vi.spyOn(api, "simulation").mockResolvedValue(record as SimulationView);
    return { ...(await mountWith(ReactionsPage)), simulation };
  }

  it("no fixed-bed section and no simulation asked for without a bed", async () => {
    const { el, unmount, simulation } = await page(ammonia);
    expect(el.querySelector("[data-reactor]")).not.toBeNull();
    expect(el.querySelector("[data-bed]")).toBeNull();
    expect(el.textContent).not.toContain("Fixed beds");
    expect(simulation).not.toHaveBeenCalled();
    unmount();
  });

  it("a failed bed is shown with its reason, not hidden", async () => {
    const { el, unmount } = await page(failed);
    expect(el.querySelector('[data-bed="R1"]')?.getAttribute("data-bed-state")).toBe("failed");
    unmount();
  });

  it("a simulation that does not load is said, not hidden", async () => {
    vi.spyOn(api, "reactions").mockResolvedValue(sim);
    vi.spyOn(api, "streams").mockRejectedValue(new Error("none"));
    vi.spyOn(api, "yaml").mockRejectedValue(new Error("none"));
    vi.spyOn(api, "kinetics").mockRejectedValue(new Error("none"));
    vi.spyOn(api, "simulation").mockRejectedValue(new ApiError(422, "process/simulation.yaml: does not load", "/api/simulation"));
    const { el, unmount } = await mountWith(ReactionsPage);
    expect(el.querySelector("[data-bed-run-error]")?.textContent).toMatch(/could not be read: process\/simulation\.yaml: does not load/);
    expect(el.querySelector('[data-bed="R1"]')).not.toBeNull();
    unmount();
  });

  it("the bed's run record from the simulation of the case", async () => {
    const { el, unmount, simulation } = await page(sim, stale);
    expect(simulation).toHaveBeenCalledWith(expect.objectContaining({ case: "" }), expect.anything());
    expect(el.querySelector('[data-bed="R1"] [data-run-state]')?.textContent).toBe("stale");
    unmount();
  });
});
