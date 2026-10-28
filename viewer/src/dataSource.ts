// Static snapshot data source: the viewer without a server. `cheme export-static DIR` writes the
// API answers of one revision as files plus `manifest.json`; this module answers the viewer's
// requests from them. The HTTP source stays the default (src/api.ts); a snapshot is opened with
// `?data=<url of the snapshot directory>` (see main.ts).
//
// Contract (core: docs/framework/static-snapshot.md): a request is named by `snapshotKey`, the
// endpoint without `/api/` (its path raw: core keys `datasheets/E 101`, where the viewer's URL
// has `datasheets/E%20101`), then `?` and the query as raw `key=value` pairs sorted by key, joined
// with `&`, leaving out empty values and `rev`. The manifest maps keys to `{file, status, type}`.

export const SNAPSHOT_SCHEMA = "cheme/viewer-snapshot/v1";

export type QueryValue = string | number | boolean | null | undefined;

export interface SnapshotEntry {
  file: string;
  status: number;
  type: string;
}

export interface SnapshotManifest {
  schema: string;
  source: { name: string | null; commit: string | null; rev: string | null; dirty: boolean; tool: string };
  limits: { max_file_bytes: number; log_limit: number };
  skipped: { path: string; bytes: number }[];
  entries: Record<string, SnapshotEntry>;
}

/**
 * The manifest key of a request; must match core's `snapshot_key`. Path segments the viewer
 * URL-encodes for HTTP (a datasheet tag) are decoded: core records the raw path.
 */
export function snapshotKey(endpoint: string, query: Record<string, QueryValue> = {}): string {
  const name = rawPath(endpoint.replace(/^\/+/, "").replace(/^api\//, ""));
  const pairs = Object.keys(query)
    .sort()
    .filter((key) => key !== "rev" && query[key] !== undefined && query[key] !== null && query[key] !== "")
    .map((key) => `${key}=${String(query[key])}`);
  return pairs.length ? `${name}?${pairs.join("&")}` : name;
}

function rawPath(path: string): string {
  try {
    return decodeURIComponent(path);
  } catch {
    return path; // a lone `%`: not encoded
  }
}

function errorResponse(status: number, message: string): Response {
  return new Response(JSON.stringify({ error: message }), { status, headers: { "content-type": "application/json" } });
}

type Fetch = typeof fetch;

export class SnapshotSource {
  readonly kind = "snapshot" as const;

  constructor(
    /** URL of the snapshot directory, ending in `/`. */
    readonly base: string,
    readonly manifest: SnapshotManifest,
    private readonly fetchImpl: Fetch = (...args) => fetch(...args),
  ) {}

  /** The snapshot's commit, short. */
  get commit(): string {
    return (this.manifest.source.commit ?? "").slice(0, 7);
  }

  /** The answer the server gave when the snapshot was written, as a Response. */
  async fetch(endpoint: string, query: Record<string, QueryValue>, signal?: AbortSignal): Promise<Response> {
    const rev = query.rev;
    if (rev !== undefined && rev !== null && rev !== "") {
      return errorResponse(404, `This is a snapshot of ${this.commit || "one revision"}; other revisions (${String(rev)}) are not included.`);
    }
    const key = snapshotKey(endpoint, query);
    const entry = this.manifest.entries[key];
    if (!entry) {
      const path = typeof query.path === "string" ? query.path : null;
      const skipped = path ? this.manifest.skipped.find((s) => s.path === path) : undefined;
      if (skipped) {
        const mb = (skipped.bytes / 1024 / 1024).toFixed(1);
        return errorResponse(404, `${path} (${mb} MB) is too large for this snapshot; open it from the repository.`);
      }
      return errorResponse(404, `Not included in this static snapshot (${key}).`);
    }
    let response: Response;
    try {
      response = await this.fetchImpl(new URL(`data/${entry.file}`, this.base).toString(), signal ? { signal } : {});
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      return errorResponse(503, "Cannot load the snapshot file.");
    }
    if (!response.ok) return errorResponse(503, `Cannot load the snapshot file (${response.status}).`);
    const body = await response.arrayBuffer();
    return new Response(body, { status: entry.status, headers: { "content-type": entry.type } });
  }

  /** URL of a stored answer, for `<img src>`-style consumers; null when not in the snapshot. */
  url(endpoint: string, query: Record<string, QueryValue>): string | null {
    const entry = this.manifest.entries[snapshotKey(endpoint, query)];
    return entry && entry.status === 200 ? new URL(`data/${entry.file}`, this.base).toString() : null;
  }
}

/**
 * Origins other than the page's own that `?data=` may load a snapshot from: a comma-separated
 * build-time list (`VITE_SNAPSHOT_ORIGINS=https://a.example,https://b.example npm run build`),
 * empty by default.
 */
export const SNAPSHOT_ORIGINS: readonly string[] = (import.meta.env?.VITE_SNAPSHOT_ORIGINS ?? "")
  .split(",")
  .map((origin) => origin.trim().replace(/\/+$/, ""))
  .filter(Boolean);

export interface LoadOptions {
  /** URL of the page the snapshot location is relative to. */
  page?: string;
  /** Origins besides the page's own that may serve snapshots. */
  allowedOrigins?: readonly string[];
}

/**
 * The snapshot directory URL for `url` (relative to `page`), ending in `/`. Throws for a
 * location on another origin than the page's unless that origin is allowed: a link with
 * `?data=https://elsewhere/` must not show someone else's plant under this site's name.
 */
export function snapshotBase(url: string, page: string, allowedOrigins: readonly string[] = SNAPSHOT_ORIGINS): string {
  const base = new URL(url.endsWith("/") ? url : `${url}/`, page);
  const own = new URL(page).origin;
  if (base.origin !== own && !allowedOrigins.includes(base.origin)) {
    throw new Error(`Refused to open the snapshot at ${base.href}: it is not on this site (${own}). Snapshots load from the viewer's own origin only.`);
  }
  return base.toString();
}

/** Load the snapshot whose directory is at `url` (relative to the page, same origin). */
export async function loadSnapshot(url: string, fetchImpl: Fetch = (...args) => fetch(...args), options: LoadOptions = {}): Promise<SnapshotSource> {
  const base = snapshotBase(url, options.page ?? globalThis.location?.href ?? "http://localhost/", options.allowedOrigins);
  const response = await fetchImpl(new URL("manifest.json", base).toString());
  if (!response.ok) throw new Error(`No snapshot at ${base} (${response.status}).`);
  let manifest: SnapshotManifest;
  try {
    manifest = (await response.json()) as SnapshotManifest;
  } catch {
    // static hosts often answer unknown paths with the app's index.html
    throw new Error(`No snapshot at ${base} (manifest.json is not JSON).`);
  }
  if (manifest?.schema !== SNAPSHOT_SCHEMA) {
    throw new Error(`Unsupported snapshot ${manifest?.schema ?? "(no schema)"} at ${base}; this viewer reads ${SNAPSHOT_SCHEMA}.`);
  }
  return new SnapshotSource(base, manifest, fetchImpl);
}
