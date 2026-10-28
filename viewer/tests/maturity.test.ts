/**
 * Evidence-based maturity (src/lib/maturity.ts, `loadMaturity` in src/store.ts) on core's real
 * `cheme maturity --json` of the ASU (tests/fixtures/api/maturity-asu.json: no level reached,
 * its engineering requirements passing, a `basic-engineering` claim that exceeds the evidence).
 */
import { afterEach, describe, expect, it } from "vitest";
import { setFetch, type MaturityReport } from "@/api";
import {
  checkInputs,
  evaluatedState,
  fingerprint,
  LEVELS,
  levelReason,
  levelScope,
  levelState,
  maturityBadge,
  parseReport,
  recordedState,
} from "@/lib/maturity";
import { loadMaturity, maturity, resetMaturity, store } from "@/store";
import asuJson from "./fixtures/api/maturity-asu.json";

const asu = (): MaturityReport => structuredClone(asuJson) as unknown as MaturityReport;

/** The ASU's report as if its sourced and balanced requirements passed: core's shape, level `balanced`. */
function balanced(): MaturityReport {
  const report = asu();
  for (const level of report.levels.slice(0, 2)) {
    for (const r of level.requirements) if (r.required) r.status = "pass";
    level.status = "pass";
    level.reached = true;
  }
  report.level = "balanced";
  report.level_index = 2;
  report.library_maturity = "screening";
  return report;
}

const bytes = (text: string) => new TextEncoder().encode(text);

describe("levels", () => {
  it("names the four cumulative levels as core orders them", () => {
    expect(asu().levels.map((l) => l.id)).toEqual(LEVELS.map((l) => l.id));
    expect(LEVELS.map((l) => l.name)).toEqual(["Sourced", "Balanced", "Predictive", "Engineering"]);
  });

  it("never describes the engineering level as verified detailed engineering", () => {
    expect(levelScope("engineering")).toBe("Preliminary/basic engineering package (not verified detailed engineering)");
    expect(maturityBadge(evaluatedState({ ...asu(), level: "engineering" }, "live")).title).toContain("not verified detailed engineering");
  });

  it("reads core's statuses: the ASU reaches no level, its passing engineering requirements do not promote it", () => {
    const report = asu();
    expect(report.levels.map(levelState)).toEqual(["not-achieved", "not-achieved", "not-achieved", "not-achieved"]);
    const engineering = report.levels[3]!;
    expect(engineering.status).toBe("pass");
    expect(levelReason(engineering, report.levels)).toBe("Its own requirements pass, but Sourced below it is not achieved (the levels are cumulative).");
    expect(levelReason(report.levels[2]!, report.levels)).toBe("11 required requirements not passing: 9 missing, 2 fail.");
  });

  it("achieved only when core reports it reached; unsupported blockers are not assessable; above evaluated_through not evaluated", () => {
    const report = balanced();
    expect(report.levels.map(levelState)).toEqual(["achieved", "achieved", "not-achieved", "not-achieved"]);
    const predictive = report.levels[2]!;
    for (const r of predictive.requirements) r.status = r.id === "predictive.property-regime" ? "unsupported" : "pass";
    expect(levelState(predictive)).toBe("not-assessable");
    expect(levelState({ ...predictive, status: "not-evaluated", requirements: [], reached: false })).toBe("not-evaluated");
    // `reached` without a passing status is not taken as achieved
    expect(levelState({ ...report.levels[0]!, status: "fail", reached: true })).not.toBe("achieved");
  });
});

describe("the badge", () => {
  it("says Not established, neutrally, when no level is reached", () => {
    const badge = maturityBadge(evaluatedState(asu(), "live"));
    expect(badge.text).toBe("Verified maturity: Not established");
    expect(badge.tone).toBe("");
  });

  it("shows the reached level of a current report", () => {
    const badge = maturityBadge(evaluatedState(balanced(), "live"));
    expect(badge.text).toBe("Verified maturity: Balanced");
    expect(badge.tone).toBe("pass");
    expect(badge.title).toContain("never raise it");
  });

  it("never shows a level for missing, incompatible, failed, stale or unconfirmed reports", () => {
    const states = [
      { kind: "missing", message: "none" },
      evaluatedState({ schema: "cheme/maturity-report/v2", levels: [] }, "live"),
      { kind: "error", message: "cannot evaluate" },
      recordedState(balanced(), { matching: [], changed: ["process/flowsheet.yaml"], unreadable: [] }),
      recordedState(balanced(), { matching: ["plant.yaml"], changed: [], unreadable: ["process/simulation-run.json"] }),
      recordedState(balanced(), null),
    ] as const;
    const texts = states.map((s) => maturityBadge(s).text);
    expect(texts).toEqual([
      "Verified maturity: no report",
      "Verified maturity: incompatible report",
      "Verified maturity: unavailable",
      "Verified maturity: outdated report",
      "Verified maturity: unconfirmed",
      "Verified maturity: unconfirmed",
    ]);
    for (const s of states) expect(maturityBadge(s).tone).not.toBe("pass");
  });

  it("rejects reports of another schema", () => {
    expect(parseReport({ schema: "cheme/maturity-report/v2" })).toEqual({ incompatible: "cheme/maturity-report/v2" });
    expect(parseReport([])).toEqual({ incompatible: "not a maturity report" });
    expect("report" in parseReport(asu())).toBe(true);
    expect(parseReport({ ...asu(), levels: [{ id: "sourced" }] })).toMatchObject({ incompatible: expect.stringContaining("requirements") });
    expect(parseReport({ ...asu(), source: { fingerprints: { "plant.yaml": 1 } } })).toMatchObject({ incompatible: expect.stringContaining("fingerprints") });
  });
});

describe("recorded reports against the revision shown", () => {
  it("fingerprints as core's content_fingerprint (CRLF normalised)", async () => {
    // core: content_fingerprint(b"a: 1\r\nb: \xc3\xa9\n")
    const expected = "sha256:234d7420d44d61c6f8b418724b2f70b4a2ebe855b642421746f31498aba89c0c";
    expect(await fingerprint(bytes("a: 1\r\nb: é\n"))).toBe(expected);
    expect(await fingerprint(bytes("a: 1\nb: é\n"))).toBe(expected);
  });

  it("sorts inputs into matching, changed (or deleted) and unreadable", async () => {
    const same = await fingerprint(bytes("x"));
    const result = await checkInputs({ "a.yaml": same, "b.yaml": same, "c.yaml": same, "d.yaml": same }, async (path) => {
      if (path === "a.yaml") return bytes("x");
      if (path === "b.yaml") return bytes("y");
      if (path === "c.yaml") return null;
      throw new Error("too large");
    });
    expect(result).toEqual({ matching: ["a.yaml"], changed: ["b.yaml", "c.yaml"], unreadable: ["d.yaml"] });
    expect(recordedState(asu(), result)).toMatchObject({ currency: "stale" });
    expect(recordedState(asu(), { matching: ["a.yaml"], changed: [], unreadable: [] })).toMatchObject({ currency: "current" });
  });
});

describe("loadMaturity", () => {
  afterEach(() => {
    resetMaturity();
    setFetch((...args) => fetch(...args));
    store.snapshot = null;
  });

  /** A fake server: `/api/maturity` and `/api/file?path=&rev=` from `files[rev][path]`. */
  function server(opts: { live?: unknown; files?: Record<string, Record<string, string>> }, calls: string[] = []) {
    setFetch((async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://viewer.test");
      calls.push(url.pathname + url.search);
      if (url.pathname === "/api/maturity")
        return opts.live === undefined ? new Response('{"error":"not found"}', { status: 404 }) : Response.json(opts.live);
      if (url.pathname === "/api/file") {
        const body = opts.files?.[url.searchParams.get("rev") ?? ""]?.[url.searchParams.get("path") ?? ""];
        return body === undefined ? new Response('{"error":"does not exist"}', { status: 404 }) : new Response(body);
      }
      return new Response("{}", { status: 404 });
    }) as typeof fetch);
  }

  async function recorded(report: MaturityReport, files: Record<string, string>): Promise<string> {
    report.source = { commit: "b63c88d", dirty: [], fingerprints: {} };
    for (const [path, text] of Object.entries(files)) report.source.fingerprints[path] = await fingerprint(bytes(text));
    return JSON.stringify(report);
  }

  it("evaluates the working tree live", async () => {
    server({ live: balanced() });
    const state = await loadMaturity(undefined);
    expect(state).toMatchObject({ kind: "report", origin: "live", currency: "current" });
    expect(maturityBadge(maturity[""]!).text).toBe("Verified maturity: Balanced");
  });

  it("reads another revision's checks/maturity.json and shows it as current only when its inputs match", async () => {
    const report = await recorded(balanced(), { "process/flowsheet.yaml": "v1" });
    server({
      live: asu(),
      files: {
        v1: { "checks/maturity.json": report, "process/flowsheet.yaml": "v1" },
        v2: { "checks/maturity.json": report, "process/flowsheet.yaml": "v2" },
      },
    });
    await Promise.all([loadMaturity(undefined), loadMaturity("v1"), loadMaturity("v2"), loadMaturity("v3")]);
    expect(maturityBadge(maturity[""]!).text).toBe("Verified maturity: Not established");
    expect(maturity.v1).toMatchObject({ currency: "current", origin: "recorded" });
    expect(maturityBadge(maturity.v1!)).toMatchObject({ text: "Verified maturity: Balanced (recorded)", tone: "info" });
    expect(maturity.v2).toMatchObject({ currency: "stale", inputs: { changed: ["process/flowsheet.yaml"] } });
    expect(maturityBadge(maturity.v2!).text).toBe("Verified maturity: outdated report");
    expect(maturity.v3).toMatchObject({ kind: "missing" });
  });

  it("falls back to the recorded report on an older server, and loads each revision once", async () => {
    const calls: string[] = [];
    const report = await recorded(asu(), { "plant.yaml": "name: x\n" });
    server({ files: { "": { "checks/maturity.json": report, "plant.yaml": "name: x\r\n" } } }, calls);
    await loadMaturity(undefined);
    await loadMaturity(undefined);
    expect(maturity[""]).toMatchObject({ kind: "report", origin: "recorded", currency: "current" });
    expect(calls.filter((c) => c === "/api/maturity")).toHaveLength(1);
  });

  it("marks an input it cannot compare in a snapshot as unconfirmed, not as changed", async () => {
    store.snapshot = { commit: "abc", tool: "cheme-as-code", dirty: false };
    const report = await recorded(balanced(), { "process/simulation-run.json": "{}" });
    server({ files: { "": { "checks/maturity.json": report } } });
    const state = await loadMaturity(undefined);
    expect(state).toMatchObject({ currency: "unverified", inputs: { unreadable: ["process/simulation-run.json"] } });
  });

  it("marks an input the server will not serve (too large, binary) as unconfirmed", async () => {
    const report = await recorded(balanced(), { "process/simulation-run.json": "{}" });
    setFetch((async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://viewer.test").searchParams.get("path");
      if (path === "checks/maturity.json") return new Response(report);
      return new Response('{"error":"process/simulation-run.json is larger than 5 MB"}', { status: 400 });
    }) as typeof fetch);
    expect(await loadMaturity("v1")).toMatchObject({ currency: "unverified", inputs: { unreadable: ["process/simulation-run.json"] } });
  });

  it("reports an incompatible or unreadable report as such", async () => {
    server({ live: { schema: "cheme/maturity-report/v0" }, files: { old: { "checks/maturity.json": "not json" } } });
    expect(await loadMaturity(undefined)).toMatchObject({ kind: "incompatible", schema: "cheme/maturity-report/v0" });
    expect(await loadMaturity("old")).toMatchObject({ kind: "incompatible", schema: "not JSON" });
  });
});
