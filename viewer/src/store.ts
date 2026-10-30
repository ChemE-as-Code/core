import { computed, reactive, watchEffect, type ComputedRef } from "vue";
import { api, ApiError, type Branch, type IssuesReport, type PlantsIndex, type PlantStatus, type RepoInfo } from "@/api";
import { hasInterlocks } from "@/lib/causeEffect";
import { datasheetPaths } from "@/lib/studies";
import { MATURITY_FILE, checkInputs, evaluatedState, recordedState, type MaturityState } from "@/lib/maturity";
import type { SnapshotManifest } from "@/dataSource";

/** The source of the static snapshot the viewer shows (`?data=`), as its header names it. */
export type SnapshotInfo = Pick<SnapshotManifest["source"], "commit" | "tool" | "dirty">;

/** Repository-wide state shared by the header, the sidebar and the views. */
export interface Store {
  repo: RepoInfo | null;
  branches: Branch[];
  error: string | null;
  loading: boolean;
  /** The working tree has `control/cause-effect.yaml` (from `/api/tree`): the C&E page has something to show. */
  hasInterlocks: boolean;
  /** The working tree has `equipment/datasheets/<TAG>.yaml` (from the same `/api/tree`): the datasheet pages have something to show. */
  hasDatasheets: boolean;
  /** The file paths of the working tree (the same `/api/tree`), null until loaded: the navigation lists the documents in it. */
  paths: Set<string> | null;
  /** The `/api/tree` request has answered or failed: until then, a page cannot tell an empty section from one still loading. */
  treeSettled: boolean;
  /** Set when the viewer shows a static snapshot (`?data=`) instead of a server. */
  snapshot: SnapshotInfo | null;
  /** Why the snapshot asked for with `?data=` could not be opened. */
  snapshotError: string | null;
  /** `?embed=1`: framed by another page (the Process Atlas), so no header and no file tree. */
  embed: boolean;
  /** The plant's id on a library server (`/p/<id>/`, core's ADR 0034); null for a server of one plant. */
  plant: string | null;
  /** The library's plants, for the switcher in the header (loaded once, when there is a plant). */
  plants: PlantsIndex | null;
  /** `?back=`: the page this snapshot was opened from (the Process Atlas), to link back to. */
  back: { href: string; label: string } | null;
  /** `GET /api/status` of the working tree, once loaded (see {@link loadStatus}). */
  status: PlantStatus | null;
  /** Why it is not there: a snapshot or an older server (404), or a failure. */
  statusError: string | null;
  statusLoading: boolean;
  /** `GET /api/issues`, once loaded (see {@link loadIssues}): the issues page and the "New issue" links. */
  issues: IssuesReport | null;
}

export const store = reactive<Store>({
  repo: null,
  branches: [],
  error: null,
  loading: false,
  hasInterlocks: false,
  hasDatasheets: false,
  paths: null,
  treeSettled: false,
  snapshot: null,
  snapshotError: null,
  embed: false,
  plant: null,
  plants: null,
  back: null,
  status: null,
  statusError: null,
  statusLoading: false,
  issues: null,
});

let issuesRequest: Promise<IssuesReport> | null = null;

/**
 * Load `/api/issues` once per session (it reads GitHub); `force` loads it again. Rejects with
 * the ApiError (404: the plant tracks no issues or a snapshot without them; 503: GitHub cannot be
 * read), leaving `store.issues` null, so the "New issue" links stay hidden.
 */
export function loadIssues(force = false): Promise<IssuesReport> {
  if (issuesRequest && !force) return issuesRequest;
  const request = api.issues().then(
    (report) => {
      if (issuesRequest === request) store.issues = report;
      return report;
    },
    (e: unknown) => {
      if (issuesRequest === request) store.issues = null;
      throw e;
    },
  );
  issuesRequest = request;
  return request;
}

/**
 * The issues for "New issue" links: loads `/api/issues` once when `/api/repo` reports
 * `has_issues` (never per click); null until then, without issues, or when they cannot be read.
 */
export function useIssues(): ComputedRef<IssuesReport | null> {
  watchEffect(() => {
    if (store.repo?.has_issues && !store.issues) void loadIssues().catch(() => {});
  });
  return computed(() => (store.repo?.has_issues ? store.issues : null));
}

let statusRequest: Promise<PlantStatus | null> | null = null;

/**
 * Load `/api/status` once per session (it validates the whole plant, which takes seconds on a
 * large one); `force` loads it again. Resolves to null when there is none (404) or it failed.
 */
export function loadStatus(force = false): Promise<PlantStatus | null> {
  if (statusRequest && !force) return statusRequest;
  store.statusLoading = true;
  const request = api
    .status()
    .then((status) => {
      if (statusRequest === request) {
        store.status = status;
        store.statusError = null;
      }
      return status;
    })
    .catch((e: unknown) => {
      if (statusRequest === request) {
        store.status = null;
        store.statusError =
          e instanceof ApiError && e.status === 404
            ? store.snapshot
              ? "This static snapshot has no status (cheme status)."
              : "This server has no /api/status (an older cheme serve)."
            : e instanceof Error
              ? e.message
              : String(e);
      }
      return null;
    })
    .finally(() => {
      if (statusRequest === request) store.statusLoading = false;
    });
  statusRequest = request;
  return request;
}

/**
 * The maturity state per revision (`""`: the working tree), see {@link loadMaturity}. Keyed by
 * revision so a page never shows one revision's maturity under another's label.
 */
export const maturity = reactive<Record<string, MaturityState>>({});
const maturityRequests = new Map<string, Promise<MaturityState>>();

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** `checks/maturity.json` at `rev`, its inputs compared with the files there. */
async function recordedMaturity(rev: string | undefined, fallback: string): Promise<MaturityState> {
  let text: string;
  try {
    text = await api.file(MATURITY_FILE, rev);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return { kind: "missing", message: fallback };
    return { kind: "error", message: message(e) };
  }
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return { kind: "incompatible", schema: "not JSON", origin: "recorded" };
  }
  const fingerprints = (data as { source?: { fingerprints?: unknown } } | null)?.source?.fingerprints;
  const inputs =
    fingerprints && typeof fingerprints === "object"
      ? await checkInputs(fingerprints as Record<string, string>, (path) =>
          api.fileBytes(path, rev).catch((e: unknown) => {
            if (e instanceof ApiError && e.status === 404 && !store.snapshot) return null; // deleted since
            throw e; // too large, binary, or not in the snapshot: cannot tell
          }),
        )
      : null;
  return recordedState(data, inputs);
}

async function evaluateMaturity(rev: string | undefined): Promise<MaturityState> {
  const where = rev ? `at ${rev}` : "in the working tree";
  const none = `No maturity report: the server evaluates the working tree only, and there is no ${MATURITY_FILE} ${where} (cheme maturity --write).`;
  if (!rev) {
    try {
      return evaluatedState(await api.maturity(), store.snapshot ? "snapshot" : "live");
    } catch (e) {
      // 404: an older server or a snapshot without it; fall back to the recorded report
      if (!(e instanceof ApiError && e.status === 404)) return { kind: "error", message: message(e) };
    }
    return recordedMaturity(rev, store.snapshot ? `This snapshot holds no maturity report (cheme export-static of a working tree without --exclude stores one), and no ${MATURITY_FILE}.` : none);
  }
  return recordedMaturity(rev, none);
}

/**
 * The maturity of `rev` (undefined: the working tree), once per session and revision; `force`
 * evaluates again. The working tree asks `GET /api/maturity` (evaluated live), any other
 * revision reads its `checks/maturity.json`, shown as current only when its inputs match.
 */
export function loadMaturity(rev: string | undefined, force = false): Promise<MaturityState> {
  const key = rev ?? "";
  const pending = maturityRequests.get(key);
  if (pending && !force) return pending;
  if (!maturity[key] || force) maturity[key] = { kind: "loading" };
  const request = evaluateMaturity(rev).then((state) => {
    if (maturityRequests.get(key) === request) maturity[key] = state;
    return state;
  });
  maturityRequests.set(key, request);
  return request;
}

/** Forget the loaded maturity (tests). */
export function resetMaturity(): void {
  maturityRequests.clear();
  for (const key of Object.keys(maturity)) delete maturity[key];
}

let repoSettled: () => void = () => {};
const repoReady = new Promise<void>((resolve) => (repoSettled = resolve));

/** `/api/repo` once its first load is over (null when it failed): for views that choose an endpoint by its flags. */
export async function whenRepo(): Promise<RepoInfo | null> {
  await repoReady;
  return store.repo;
}

export async function loadRepo(): Promise<void> {
  if (store.snapshotError) {
    store.error = store.snapshotError; // ?data= asked for a snapshot: never fall back to a server
    repoSettled();
    return;
  }
  store.loading = true;
  try {
    const [repo, branches] = await Promise.all([api.repo(), api.branches()]);
    store.repo = repo;
    store.branches = branches;
    store.error = null;
    if (repo.has_datasheets) store.hasDatasheets = true;
    // /api/repo has no flag for them: the tree says (without holding up the repo, or failing it).
    void api
      .tree()
      .then((tree) => {
        store.hasInterlocks = hasInterlocks(tree);
        store.hasDatasheets = Boolean(repo.has_datasheets) || datasheetPaths(tree).size > 0;
        store.paths = new Set(tree.filter((e) => e.type === "file").map((e) => e.path));
      })
      .catch(() => {
        store.hasInterlocks = false;
        store.hasDatasheets = Boolean(repo.has_datasheets);
        store.paths = null;
      })
      .finally(() => {
        store.treeSettled = true;
      });
  } catch (e) {
    store.error = e instanceof Error ? e.message : String(e);
  } finally {
    store.loading = false;
    repoSettled();
  }
}
