import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, defineComponent, h, nextTick } from "vue";
import { RouterView, createMemoryHistory, createRouter } from "vue-router";
import { api, type LcaReport } from "@/api";
import LciReadiness from "@/components/LciReadiness.vue";
import { exchangeLines, hasReadiness, missingMetadata, pedigreeRows, readinessFindings, stateText, topicOf } from "@/lib/lciReadiness";
// An older core: no data_quality, water or balance (the section is hidden).
import oldJson from "./fixtures/api/lca-asu.json";
// A core before the balance gates: data quality and documentation, no balance.
import mainJson from "./fixtures/api/lca-asu-readiness-main.json";
// core main: with the balance and the emission estimates.
import fullJson from "./fixtures/api/lca-asu-readiness.json";
import datasetDoc from "./fixtures/api/yaml-dataset-asu.json";
import datasetText from "./fixtures/api/dataset-asu.yaml?raw";

const old = oldJson as unknown as LcaReport;
const main = mainJson as unknown as LcaReport;
const full = fullJson as unknown as LcaReport;

describe("lci readiness helpers", () => {
  it("is reported only by a core with the rating, water or balance", () => {
    expect(hasReadiness(old)).toBe(false);
    expect(hasReadiness(main)).toBe(true);
    expect(hasReadiness(full)).toBe(true);
    expect(hasReadiness(null)).toBe(false);
  });

  it("names the publication-minimum fields the ASU dataset lacks, the location among them", () => {
    const { fields, finding } = missingMetadata(main);
    expect(fields).toContain("location");
    expect(finding?.rule).toBe("cheme.lca-dataset-undocumented");
    expect(finding?.file).toBe("lca/lca.yaml");
  });

  it("groups core's findings by topic", () => {
    const found = readinessFindings(full);
    expect(found.emissions.map((f) => f.rule)).toEqual(["cheme.lci-emissions-incomplete"]);
    expect(found.emissions[0]!.ids).toEqual(["V-3101", "T-4101", "T-4102"]);
    expect(found.consumables.map((f) => f.ids[0])).toEqual(["consumable:molecular-sieve", "consumable:lube-oil"]);
    expect(found.balance.map((f) => f.rule)).toEqual(["cheme.lci-balance-unassessable"]);
    expect(found.documentation.map((f) => f.rule)).toEqual(["cheme.lca-unchecked", "cheme.lca-flow-identity", "cheme.lca-dataset-undocumented"]);
    expect(topicOf({ ...found.emissions[0]!, rule: "cheme.lca-equipment-weight" })).toBeNull();
  });

  it("finds each exchange's line in the dataset", () => {
    const lines = exchangeLines(datasetText);
    expect(lines.get("feed:AIR")).toBe(datasetText.split("\n").indexOf("- key: feed:AIR") + 1);
    expect(exchangeLines("- key: 'a:b'\n  x: 1\n- key: \"c\"\n")).toEqual(new Map([["a:b", 1], ["c", 3]]));
  });

  it("reads the pedigree core wrote per exchange", () => {
    const rows = pedigreeRows(datasetDoc.data, exchangeLines(datasetText));
    expect(rows.length).toBeGreaterThan(20);
    const air = rows.find((r) => r.key === "feed:AIR")!;
    expect(air.scores).toEqual([3, 4, 1, 5, 2]);
    expect(air.basis).toMatch(/default pedigree/);
    expect(air.line).toBeGreaterThan(0);
    expect(pedigreeRows(null)).toEqual([]);
  });

  it("says a balance not reported is not assessed", () => {
    expect(stateText("unknown")).toBe("not assessed");
    expect(stateText("not-assessable")).toBe("not assessable");
  });
});

/** Mount the section for *report* at /lca, with the dataset's text served (and its yaml, unless the test mocks it). */
async function mount(report: LcaReport, { yaml = true } = {}) {
  if (yaml) vi.spyOn(api, "yaml").mockResolvedValue(datasetDoc as never);
  vi.spyOn(api, "file").mockResolvedValue(datasetText);
  const page = defineComponent(() => () => h(LciReadiness, { report }));
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/lca", name: "lca", component: page },
      { path: "/file/:path(.*)*", name: "file", component: { render: () => h("p") } },
    ],
  });
  const el = document.createElement("div");
  document.body.appendChild(el);
  const app = createApp({ render: () => h(RouterView) });
  app.use(router);
  await router.push("/lca");
  await router.isReady();
  app.mount(el);
  for (let i = 0; i < 5; i++) await nextTick();
  await new Promise((r) => setTimeout(r, 0));
  await nextTick();
  return { el, unmount: () => (app.unmount(), el.remove()) };
}

describe("LciReadiness", () => {
  afterEach(() => vi.restoreAllMocks());

  it("is hidden for an older core without the fields", async () => {
    const yaml = vi.spyOn(api, "yaml");
    const { el, unmount } = await mount(old);
    expect(el.querySelector("[data-readiness]")).toBeNull();
    expect(yaml).not.toHaveBeenCalled();
    unmount();
  });

  it("shows the DQR, the missing metadata and closure not assessed with core main", async () => {
    const { el, unmount } = await mount(main);
    expect(el.querySelector("[data-readiness]")).not.toBeNull();
    expect(el.querySelector("[data-balance-unknown]")?.textContent).toBe("not assessed");
    expect(el.querySelector("[data-balance-not-assessed]")?.textContent).toMatch(/balance gates/);
    expect(el.querySelector('[data-readiness-card="dqr"] .card-value')?.textContent).toBe("2.67");
    expect(el.querySelector('[data-indicator="GeR"]')?.textContent).toMatch(/weakest/);
    expect(el.querySelector('[data-missing="location"]')).not.toBeNull();
    const source = el.querySelector("[data-missing-metadata] a.file") as HTMLAnchorElement;
    expect(source.getAttribute("href")).toBe("/file/lca/lca.yaml");
    // the pedigree per exchange, each linked to its line of lca/dataset.yaml
    const air = el.querySelector('[data-pedigree-row="feed:AIR"] a') as HTMLAnchorElement;
    expect(air.getAttribute("href")).toMatch(/^\/file\/lca\/dataset\.yaml\?line=\d+$/);
    expect(el.querySelectorAll('[data-pedigree-row="feed:AIR"] td.weak').length).toBe(2);
    // core main has no emission estimates yet
    expect(el.querySelector('[data-topic="emissions"]')).toBeNull();
    // consumables without disposal, linked to their line of lca/lca.yaml
    const disposal = [...el.querySelectorAll('[data-topic="consumables"] li')].find((li) => li.textContent?.includes("molecular-sieve"));
    expect(disposal?.querySelector("a")?.getAttribute("href")).toBe("/file/lca/lca.yaml?line=72");
    unmount();
  });

  it("shows the ASU's closure, DQR and missing metadata with core main, each linked to its source", async () => {
    const { el, unmount } = await mount(full);
    expect(el.querySelector('[data-source="balance"]')?.getAttribute("href")).toBe("/file/lca/dataset.yaml");
    expect(el.querySelector('[data-closure="mass"] .badge')?.textContent).toBe("closed");
    expect(el.querySelector('[data-source="dqr"]')?.getAttribute("href")).toBe("/file/lca/dataset.yaml");
    expect(el.querySelector('[data-readiness-card="dqr"] .card-value')?.textContent).toBe("2.67");
    expect(el.querySelector('[data-missing="location"]')).not.toBeNull();
    expect(el.querySelector("[data-missing-metadata] a.file")?.getAttribute("href")).toBe("/file/lca/lca.yaml");
    // the exchanges outside the balance, each linked to its line
    const concrete = [...el.querySelectorAll("[data-excluded] li")].find((li) => li.textContent?.includes("construction:concrete"));
    const line = exchangeLines(datasetText).get("construction:concrete");
    expect(line).toBeGreaterThan(0);
    expect(concrete?.querySelector("a")?.getAttribute("href")).toBe(`/file/lca/dataset.yaml?line=${line}`);
    // the ASU records no cut-off flow
    expect(el.querySelector("[data-cutoff]")).toBeNull();
    unmount();
  });

  it("lists the cut-off flows core records beside the balance", async () => {
    const cutoff = { "cutoff:gasket": { direction: "input", amount: 0.002, unit: "kg" }, "cutoff:label": { direction: "output", amount: null, unit: "kg" } } as const;
    const { el, unmount } = await mount({ ...full, balance: { ...full.balance!, cutoff } });
    expect([...el.querySelectorAll("[data-cutoff-flow]")].map((li) => li.getAttribute("data-cutoff-flow"))).toEqual(["cutoff:gasket", "cutoff:label"]);
    expect(el.querySelector("[data-cutoff] summary")?.textContent).toBe("2 cut-off flows, listed beside the balance and not counted in it");
    expect(el.querySelector('[data-cutoff-flow="cutoff:gasket"]')?.textContent).toMatch(/input, 0\.002 kg/);
    expect(el.querySelector('[data-cutoff-flow="cutoff:label"]')?.textContent).toMatch(/amount not given/);
    // not in the ASU's dataset: linked to the file without a line
    expect(el.querySelector('[data-cutoff-flow="cutoff:label"] a')?.getAttribute("href")).toBe("/file/lca/dataset.yaml");
    unmount();
  });

  it("links exchanges without a pedigree to their line, and keeps the lines when the yaml fails", async () => {
    // an exchange outside the balance, with its pedigree removed from the dataset's data
    const key = "construction:concrete";
    const line = exchangeLines(datasetText).get(key);
    const data = datasetDoc.data as { exchanges: { key: string; pedigree?: unknown }[] };
    const unrated = { ...datasetDoc, data: { ...data, exchanges: data.exchanges.map((e) => (e.key === key ? { ...e, pedigree: undefined } : e)) } };
    vi.spyOn(api, "yaml").mockResolvedValue(unrated as never);
    let mounted = await mount({ ...full, data_quality: null }, { yaml: false });
    let el = mounted.el;
    expect(el.querySelector(`[data-pedigree-row="${key}"]`)).toBeNull();
    const link = (k: string, within: string) => [...el.querySelectorAll(`${within} li`)].find((li) => li.textContent?.includes(k))?.querySelector("a") ?? null;
    expect(link(key, "[data-excluded]")?.getAttribute("href")).toBe(`/file/lca/dataset.yaml?line=${line}`);
    mounted.unmount();
    vi.restoreAllMocks();

    // the yaml does not load: no pedigree (and why), the lines still from the text
    vi.spyOn(api, "yaml").mockRejectedValue(new Error("lca/dataset.yaml: not valid YAML"));
    mounted = await mount(full, { yaml: false });
    el = mounted.el;
    expect(el.querySelector("[data-pedigree]")).toBeNull();
    expect(el.querySelector("[data-pedigree-problem]")?.textContent).toMatch(/not valid YAML/);
    expect(link(key, "[data-excluded]")?.getAttribute("href")).toBe(`/file/lca/dataset.yaml?line=${line}`);
    const lube = el.querySelector("[data-no-composition] a")?.getAttribute("href");
    expect(lube).toBe(`/file/lca/dataset.yaml?line=${exchangeLines(datasetText).get("consumable:lube-oil")}`);
    mounted.unmount();
  });

  it("asks for no dataset and links none when core reports the plant has none", async () => {
    const { el, unmount } = await mount({ ...full, balance: null, data_quality: null });
    expect(api.yaml).not.toHaveBeenCalled();
    expect(api.file).not.toHaveBeenCalled();
    expect(el.querySelector('[data-readiness-card="balance"] .card-value')?.textContent).toBe("no dataset");
    expect(el.querySelector("[data-source]")).toBeNull();
    expect(el.querySelector('[data-readiness] a[href="/file/lca/dataset.yaml"]')).toBeNull();
    unmount();
  });

  it("shows the closure states and the emission sources of core main", async () => {
    const { el, unmount } = await mount(full);
    expect(el.querySelector('[data-balance-state="lci-mass-balance"]')?.textContent).toBe("mass: closed");
    expect(el.querySelector('[data-balance-state="lci-element-balance"]')?.textContent).toBe("elements: not assessable");
    expect(el.querySelector('[data-closure="mass"]')?.textContent).toMatch(/\+0\.00 %/);
    expect([...el.querySelectorAll("[data-closure]")].map((r) => r.getAttribute("data-closure"))).toEqual(["mass", "Ar", "C", "H", "N", "O", "carbon"]);
    const noComposition = el.querySelector("[data-no-composition]")!;
    expect(noComposition.textContent).toMatch(/consumable:lube-oil/);
    expect(noComposition.querySelector("a")?.getAttribute("href")).toMatch(/^\/file\/lca\/dataset\.yaml\?line=\d+$/);
    expect(el.querySelector('[data-readiness-card="emissions"] .card-value')?.textContent).toBe("3");
    expect(el.querySelector('[data-topic="emissions"]')?.textContent).toMatch(/V-3101/);
    expect(el.querySelector('[data-topic="balance"]')?.textContent).toMatch(/lci-balance-unassessable/);
    // the findings already listed under Balance are not repeated as bare problems
    expect(el.querySelector("[data-balance-problems]")).toBeNull();
    unmount();
  });

  it("shows the water of a dataset with water flows", async () => {
    const report = { ...main, water: { basis: "1 h of operation", unit: "m3", withdrawal: 2, returned: 1.5, evaporated: 0.4, consumption: 0.5 } };
    const { el, unmount } = await mount(report);
    expect(el.querySelector("[data-water]")?.textContent).toMatch(/0\.5 m3/);
    unmount();
  });
});
