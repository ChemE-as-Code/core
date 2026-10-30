import { describe, expect, it } from "vitest";
import type { PlantEntry } from "@/api";
import { apiUrl, usePlant } from "@/api";
import { filterPlants, indexUrl, plantFromPath, plantName, safeBackUrl, switchUrl } from "@/lib/plants";

const plant = (over: Partial<PlantEntry>): PlantEntry => ({
  id: "x",
  path: "processes/x",
  name: null,
  stage: null,
  sheets: 0,
  maturity: null,
  maturity_checked: null,
  title: null,
  summary: null,
  families: [],
  error: null,
  ...over,
});

describe("plantFromPath", () => {
  it("reads the plant of a library server's page", () => {
    expect(plantFromPath("/p/asu-1/")).toEqual({ id: "asu-1", base: "/p/asu-1/" });
    expect(plantFromPath("/p/asu-1/pid/pid/P-01.xml")).toEqual({ id: "asu-1", base: "/p/asu-1/" });
    expect(plantFromPath("/p/a%20b/streams")).toEqual({ id: "a b", base: "/p/a%20b/" });
  });

  it("is null for a server of one plant", () => {
    expect(plantFromPath("/")).toBeNull();
    expect(plantFromPath("/streams")).toBeNull();
    expect(plantFromPath("/p/asu-1")).toBeNull();
    expect(plantFromPath("/pid/p/x/")).toBeNull();
  });
});

describe("the API of a plant", () => {
  it("prefixes every endpoint, and stops when the plant is unset", () => {
    usePlant("asu-1");
    expect(apiUrl("repo")).toBe("/p/asu-1/api/repo");
    expect(apiUrl("file", { path: "plant.yaml", rev: "" })).toBe("/p/asu-1/api/file?path=plant.yaml");
    usePlant(null);
    expect(apiUrl("repo")).toBe("/api/repo");
  });
});

describe("switchUrl", () => {
  it("keeps a plant-wide page and the page options, not the revision or the page's query", () => {
    expect(switchUrl("b", { name: "streams", path: "/streams" }, "?rev=main&case=summer&theme=dark")).toBe("/p/b/streams?theme=dark");
    expect(switchUrl("b", { name: "lca", path: "/lca" }, "?embed=1")).toBe("/p/b/lca?embed=1");
  });

  it("opens the overview for a page of one file, sheet or tag", () => {
    expect(switchUrl("b", { name: "pid", path: "/pid/pid/P-01.xml" }, "")).toBe("/p/b/");
    expect(switchUrl("b", { name: "datasheet", path: "/datasheets/P-101" }, "")).toBe("/p/b/");
    expect(switchUrl("b", { name: "home", path: "/" }, "")).toBe("/p/b/");
    expect(switchUrl("a b", { name: "home", path: "/" }, "")).toBe("/p/a%20b/");
  });

  it("goes back to the index with the page options", () => {
    expect(indexUrl("?theme=light&rev=x")).toBe("/?theme=light");
    expect(indexUrl("")).toBe("/");
  });
});

describe("filterPlants and plantName", () => {
  const plants = [
    plant({ id: "asu-1", name: "ASU-1", stage: "basic", families: ["air-separation"], summary: "Cryogenic air separation" }),
    plant({ id: "methanol-1", title: "Methanol synthesis", stage: "concept" }),
  ];

  it("matches every word in id, name, title, summary and families", () => {
    expect(filterPlants(plants, { text: "cryogenic asu" }).map((p) => p.id)).toEqual(["asu-1"]);
    expect(filterPlants(plants, { text: "synthesis" }).map((p) => p.id)).toEqual(["methanol-1"]);
    expect(filterPlants(plants, { family: "air-separation" }).map((p) => p.id)).toEqual(["asu-1"]);
    expect(filterPlants(plants, { stage: "concept" }).map((p) => p.id)).toEqual(["methanol-1"]);
    expect(filterPlants(plants, {})).toHaveLength(2);
  });

  it("names a plant by plant.yaml, else its title, else its id", () => {
    expect(plantName(plants[0]!)).toBe("ASU-1");
    expect(plantName(plants[1]!)).toBe("Methanol synthesis");
    expect(plantName(plant({ id: "bare" }))).toBe("bare");
  });
});

describe("safeBackUrl", () => {
  const here = "https://atlas.example/viewer/?data=/data/asu-1/";
  it("links back within this site only", () => {
    expect(safeBackUrl("/processes/asu-1/", here)).toBe("/processes/asu-1/");
    expect(safeBackUrl("https://atlas.example/processes/asu-1/#model", here)).toBe("/processes/asu-1/#model");
    for (const bad of ["https://evil.example/", "//evil.example/x", "javascript:alert(1)", "data:text/html,x", "", null])
      expect(safeBackUrl(bad, here)).toBeNull();
  });
});
