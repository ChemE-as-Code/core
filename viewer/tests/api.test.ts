import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, apiUrl, resetSession, setFetch } from "@/api";

describe("apiUrl", () => {
  it("builds a plain endpoint URL", () => {
    expect(apiUrl("repo", {}, "")).toBe("/api/repo");
  });

  it("accepts endpoints with a leading slash or api/ prefix", () => {
    expect(apiUrl("/api/branches", {}, "")).toBe("/api/branches");
    expect(apiUrl("/tree", {}, "")).toBe("/api/tree");
  });

  it("drops undefined, null and empty parameters (working tree = no rev)", () => {
    expect(apiUrl("tree", { rev: undefined }, "")).toBe("/api/tree");
    expect(apiUrl("file", { path: "a.md", rev: "" }, "")).toBe("/api/file?path=a.md");
    expect(apiUrl("file", { path: "a.md", rev: null }, "")).toBe("/api/file?path=a.md");
  });

  it("sorts and encodes parameters", () => {
    expect(apiUrl("pid.svg", { rev: "feat/x y", path: "pid/P 01&.xml" }, "")).toBe(
      "/api/pid.svg?path=pid%2FP+01%26.xml&rev=feat%2Fx+y",
    );
    expect(apiUrl("log", { path: "pid/P-01.xml", limit: 50 }, "")).toBe("/api/log?limit=50&path=pid%2FP-01.xml");
  });

  it("prefixes a base URL without doubling slashes", () => {
    expect(apiUrl("repo", {}, "http://127.0.0.1:8765/")).toBe("http://127.0.0.1:8765/api/repo");
  });
});

describe("api client", () => {
  const calls: string[] = [];
  const respond = (body: unknown, init: ResponseInit = {}) =>
    setFetch(async (input) => {
      calls.push(String(input));
      const text = typeof body === "string" ? body : JSON.stringify(body);
      return new Response(text, { status: 200, ...init });
    });

  afterEach(() => {
    calls.length = 0;
    vi.restoreAllMocks();
  });

  it("requests the documented URLs", async () => {
    respond([]);
    await api.tree();
    await api.tree("main");
    await api.log({ path: "pid/P-01.xml" });
    await api.diff("pid/P-01.xml", "HEAD~1");
    await api.diff("pid/P-01.xml", "abc", "def");
    await api.checks();
    await api.yaml("equipment/equipment-list.yaml", "v1");
    await api.layout();
    await api.layout("feat/x");
    expect(calls).toEqual([
      "/api/tree",
      "/api/tree?rev=main",
      "/api/log?limit=50&path=pid%2FP-01.xml",
      "/api/diff?old=HEAD%7E1&path=pid%2FP-01.xml",
      "/api/diff?new=def&old=abc&path=pid%2FP-01.xml",
      "/api/checks",
      "/api/yaml?path=equipment%2Fequipment-list.yaml&rev=v1",
      "/api/layout",
      "/api/layout?rev=feat%2Fx",
    ]);
    expect(api.pidSvgUrl("pid/P-01.xml")).toBe("/api/pid.svg?path=pid%2FP-01.xml");
  });

  it("returns text for file and svg endpoints", async () => {
    respond("<svg/>", { headers: { "Content-Type": "image/svg+xml" } });
    await expect(api.pidSvg("pid/P-01.xml")).resolves.toBe("<svg/>");
  });

  it("turns JSON errors into ApiError with the server message", async () => {
    respond({ error: "cannot load pid/P-01.xml" }, { status: 422 });
    const error = await api.pidSvg("pid/P-01.xml").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(422);
    expect((error as ApiError).message).toBe("cannot load pid/P-01.xml");
  });

  it("reports a missing layout as a 404 ApiError", async () => {
    respond({ error: "no layout files at main" }, { status: 404 });
    const error = (await api.layout("main").catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(404);
    expect(error.message).toBe("no layout files at main");
  });

  it("reports an unreachable server", async () => {
    setFetch(async () => {
      throw new TypeError("Failed to fetch");
    });
    const error = (await api.repo().catch((e: unknown) => e)) as ApiError;
    expect(error.status).toBe(0);
    expect(error.message).toMatch(/cheme serve/);
  });

  it("runs the checks with a POST carrying the session token, and refreshes a stale token", async () => {
    resetSession();
    const seen: { url: string; method: string; token: string | null }[] = [];
    let tokens = ["t1", "t2"];
    let accepted = "t2";
    setFetch(async (input, init) => {
      const url = String(input);
      const headers = new Headers(init?.headers);
      seen.push({ url, method: init?.method ?? "GET", token: headers.get("X-Cheme-Token") });
      if (url === "/api/session") {
        const token = tokens.shift();
        return new Response(JSON.stringify({ token, header: "X-Cheme-Token" }));
      }
      if (headers.get("X-Cheme-Token") !== accepted) {
        return new Response(JSON.stringify({ error: "wrong token" }), { status: 403 });
      }
      return new Response(JSON.stringify({ checks: [] }));
    });
    await expect(api.runChecks()).resolves.toEqual({ checks: [] });
    expect(seen).toEqual([
      { url: "/api/session", method: "GET", token: null },
      { url: "/api/checks/run", method: "POST", token: "t1" },
      { url: "/api/session", method: "GET", token: null },
      { url: "/api/checks/run", method: "POST", token: "t2" },
    ]);
    // The token is cached; a second refusal is reported, not retried forever.
    seen.length = 0;
    await api.runChecks();
    expect(seen.map((c) => c.url)).toEqual(["/api/checks/run"]);
    accepted = "never";
    tokens = ["t3"];
    const error = (await api.runChecks().catch((e: unknown) => e)) as ApiError;
    expect(error.status).toBe(403);
  });
});
