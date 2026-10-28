import { afterEach, describe, expect, it } from "vitest";
import { api, ApiError, currentSnapshot, useSnapshot } from "@/api";
import { loadSnapshot, SNAPSHOT_SCHEMA, snapshotBase, snapshotKey, SnapshotSource, type SnapshotManifest } from "@/dataSource";

const BASE = "https://atlas.example/data/asu-1/snapshot/";
/** The viewer page on the same site as the snapshot. */
const PAGE = { page: "https://atlas.example/viewer/?data=x" };

function manifest(entries: SnapshotManifest["entries"], skipped: SnapshotManifest["skipped"] = []): SnapshotManifest {
  return {
    schema: SNAPSHOT_SCHEMA,
    source: { name: "ASU-1", commit: "2c3da961e77bf14ba5c38c18c4aaf22b082e18a3", rev: null, dirty: false, tool: "cheme-as-code 0.7.0" },
    limits: { max_file_bytes: 2097152, log_limit: 50 },
    skipped,
    entries,
  };
}

/** A fake static host: path -> body. */
function host(files: Record<string, string>, calls: string[] = []): typeof fetch {
  return (async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    const path = url.replace(BASE, "");
    return path in files ? new Response(files[path]) : new Response("nope", { status: 404 });
  }) as typeof fetch;
}

afterEach(() => useSnapshot(null));

describe("snapshotKey (same cases as core's tests/test_export_static.py)", () => {
  it("matches core", () => {
    expect(snapshotKey("repo")).toBe("repo");
    expect(snapshotKey("/api/pid.svg", { path: "pid/P-01.xml", rev: "abc" })).toBe("pid.svg?path=pid/P-01.xml");
    expect(snapshotKey("log", { path: null, limit: 50 })).toBe("log?limit=50");
    expect(snapshotKey("layout/plan.svg", { z: "", level: "L0" })).toBe("layout/plan.svg?level=L0");
    expect(snapshotKey("streams", { rev: "x", case: "design" })).toBe("streams?case=design");
    expect(snapshotKey("file", { path: "docs/a b&c.md" })).toBe("file?path=docs/a b&c.md");
  });

  it("keys an encoded path segment by its raw value, as core records it (pre-release viewer issue 46)", () => {
    expect(snapshotKey(`datasheets/${encodeURIComponent("E 101")}`)).toBe("datasheets/E 101");
    expect(snapshotKey(`datasheets/${encodeURIComponent("W-Ü1&2")}.svg`, { generated: undefined })).toBe("datasheets/W-Ü1&2.svg");
    expect(snapshotKey(`datasheets/${encodeURIComponent("A%B")}`)).toBe("datasheets/A%B");
    expect(snapshotKey("datasheets/100%")).toBe("datasheets/100%");
  });
});

describe("SnapshotSource", () => {
  const files = { "data/r.json": '{"name":"ASU-1"}', "data/p.svg": "<svg/>", "data/l.json": '{"error":"no lca"}' };
  const source = () =>
    new SnapshotSource(
      BASE,
      manifest(
        {
          repo: { file: "r.json", status: 200, type: "application/json" },
          "pid.svg?path=pid/P-01.xml": { file: "p.svg", status: 200, type: "image/svg+xml" },
          lca: { file: "l.json", status: 422, type: "application/json" },
        },
        [{ path: "layout/plant-model.yaml", bytes: 2_891_225 }],
      ),
      host(files),
    );

  it("answers stored requests with their status and type", async () => {
    const repo = await source().fetch("repo", {});
    expect(repo.status).toBe(200);
    expect(await repo.json()).toEqual({ name: "ASU-1" });
    const svg = await source().fetch("pid.svg", { path: "pid/P-01.xml" });
    expect(svg.headers.get("content-type")).toBe("image/svg+xml");
    const lca = await source().fetch("lca", {});
    expect(lca.status).toBe(422);
  });

  it("refuses other revisions and says what is missing", async () => {
    const other = await source().fetch("repo", { rev: "main" });
    expect(other.status).toBe(404);
    expect((await other.json()).error).toMatch(/snapshot of 2c3da96/);
    const missing = await source().fetch("yaml", { path: "nope.yaml" });
    expect((await missing.json()).error).toMatch(/Not included in this static snapshot \(yaml\?path=nope.yaml\)/);
    const big = await source().fetch("yaml", { path: "layout/plant-model.yaml" });
    expect((await big.json()).error).toMatch(/2\.8 MB\) is too large/);
  });

  it("gives image URLs of stored drawings", () => {
    expect(source().url("pid.svg", { path: "pid/P-01.xml" })).toBe(`${BASE}data/p.svg`);
    expect(source().url("pid.svg", { path: "pid/P-09.xml" })).toBeNull();
    expect(source().url("lca", {})).toBeNull();
  });
});

describe("loadSnapshot", () => {
  it("reads the manifest relative to the snapshot directory", async () => {
    const calls: string[] = [];
    const loaded = await loadSnapshot(BASE.slice(0, -1), host({ "manifest.json": JSON.stringify(manifest({})) }, calls), PAGE);
    expect(calls).toEqual([`${BASE}manifest.json`]);
    expect(loaded.base).toBe(BASE);
    expect(loaded.commit).toBe("2c3da96");
  });

  it("rejects other schemas and missing snapshots", async () => {
    await expect(loadSnapshot(BASE, host({ "manifest.json": '{"schema":"other/v9"}' }), PAGE)).rejects.toThrow(/Unsupported snapshot other\/v9/);
    await expect(loadSnapshot(BASE, host({}), PAGE)).rejects.toThrow(/No snapshot at/);
    await expect(loadSnapshot(BASE, host({ "manifest.json": "<!doctype html><html></html>" }), PAGE)).rejects.toThrow(/manifest.json is not JSON/);
  });

  it("refuses a snapshot on another origin without requesting it", async () => {
    const calls: string[] = [];
    const page = { page: "https://atlas.example/viewer/?data=x" };
    for (const foreign of ["https://other.example/snap/", "//other.example/snap/", "http://atlas.example/data/", "data:application/json,{}"]) {
      await expect(loadSnapshot(foreign, host({}, calls), page)).rejects.toThrow(/Refused to open the snapshot .* not on this site \(https:\/\/atlas\.example\)/);
    }
    expect(calls).toEqual([]);
  });
});

describe("snapshotBase", () => {
  const page = "https://atlas.example/viewer/?data=../data/asu-1/snapshot/#/pid";

  it("resolves relative and same-origin locations against the page", () => {
    expect(snapshotBase("../data/asu-1/snapshot/", page)).toBe(BASE);
    expect(snapshotBase("/data/asu-1/snapshot", page)).toBe(BASE);
    expect(snapshotBase(BASE, page)).toBe(BASE);
  });

  it("allows other origins only when listed", () => {
    expect(() => snapshotBase("https://cdn.example/snap/", page)).toThrow(/not on this site/);
    expect(snapshotBase("https://cdn.example/snap/", page, ["https://cdn.example"])).toBe("https://cdn.example/snap/");
    expect(() => snapshotBase("https://cdn.example.evil/snap/", page, ["https://cdn.example"])).toThrow(/not on this site/);
  });
});

describe("api in snapshot mode", () => {
  it("answers the viewer's calls from the snapshot", async () => {
    const source = new SnapshotSource(
      BASE,
      manifest({
        repo: { file: "r.json", status: 200, type: "application/json" },
        "streams?case=design": { file: "s.json", status: 200, type: "application/json" },
        lca: { file: "l.json", status: 422, type: "application/json" },
      }),
      host({ "data/r.json": '{"name":"ASU-1"}', "data/s.json": '{"streams":[]}', "data/l.json": '{"error":"LCA does not compute"}' }),
    );
    useSnapshot(source);
    expect(currentSnapshot()).toBe(source);
    expect((await api.repo()).name).toBe("ASU-1");
    expect(await api.streams({ case: "design" })).toEqual({ streams: [] });

    const failure = await api.lca().catch((e: unknown) => e);
    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(422);
    expect((failure as ApiError).message).toBe("LCA does not compute");

    const diff = await api.diff("pid/P-01.xml", "HEAD").catch((e: unknown) => e);
    expect((diff as ApiError).status).toBe(405);
    await expect(api.runChecks()).rejects.toThrow(/needs a running server/);
    await expect(api.repo.call(null)).resolves.toBeTruthy();
    await expect(api.tree("main")).rejects.toThrow(/other revisions \(main\)/);
  });
});
