/**
 * Pure helpers for the process views: grouped sheets, the stream table and BFD/PFD picks.
 */
import type { ProcessBalance, ProcessNode, ProcessStream, ProcessValue, Provenance, Sheet, StreamTable } from "@/api";

export interface SheetGroup {
  id: "process" | "pid";
  title: string;
  sheets: Sheet[];
}

const PROCESS_ORDER: Record<string, number> = { bfd: 0, pfd: 1 };

/** Process sheets (BFD before PFD) first, then the P&IDs; empty groups are left out. */
export function groupSheets(sheets: Sheet[]): SheetGroup[] {
  const process = sheets
    .map((sheet, index) => ({ sheet, index }))
    .filter(({ sheet }) => sheet.kind === "bfd" || sheet.kind === "pfd")
    .sort((a, b) => PROCESS_ORDER[a.sheet.kind!]! - PROCESS_ORDER[b.sheet.kind!]! || a.index - b.index)
    .map(({ sheet }) => sheet);
  const pids = sheets.filter((s) => !s.kind || s.kind === "pid");
  const groups: SheetGroup[] = [];
  if (process.length) groups.push({ id: "process", title: "Process", sheets: process });
  if (pids.length) groups.push({ id: "pid", title: "P&IDs", sheets: pids });
  return groups;
}

export function isProcessSheet(sheet: Sheet | undefined | null): boolean {
  return sheet?.kind === "bfd" || sheet?.kind === "pfd";
}

export const KIND_BADGE: Record<string, string> = { bfd: "BFD", pfd: "PFD", pid: "P&ID" };

export const PROVENANCE_SHORT: Record<Provenance, string> = { given: "G", assumed: "A", calculated: "C" };

/** `1000 kg/h`, with up to 6 significant digits. */
export function formatValue(value: ProcessValue | null | undefined): string {
  if (!value) return "";
  return `${formatNumber(value.value)} ${value.unit}`.trim();
}

export function formatNumber(n: number): string {
  if (!Number.isFinite(n)) return String(n);
  return String(Number(n.toPrecision(6)));
}

export function formatComposition(stream: ProcessStream): string {
  const c = stream.composition;
  if (!c) return "";
  const basis = c.basis === "mole_fraction" ? "mol" : c.basis === "mass_fraction" ? "mass" : c.basis;
  return `${basis}: ${Object.entries(c.values)
    .map(([k, v]) => `${k} ${formatNumber(v)}`)
    .join(", ")}`;
}

export function formatPhase(stream: ProcessStream): string {
  const p = stream.phase;
  if (!p) return "";
  return p.vapor_fraction != null ? `${p.value} (vf ${formatNumber(p.vapor_fraction)})` : p.value;
}

/** Whether any value of the stream is stale (a calculated value or the phase). */
export function isStale(stream: ProcessStream): boolean {
  return stream.stale.length > 0;
}

/** Row status of a stream: `error` (crosses a failing balance), `stale`, or `ok`. */
export function streamStatus(stream: ProcessStream): "error" | "stale" | "ok" {
  if (stream.imbalance.length) return "error";
  if (isStale(stream)) return "stale";
  return "ok";
}

export type StreamFilter = "all" | "bfd" | "problems";

/** Streams matching *text* (id, title, ends, blocks) and *which* (all, BFD-visible, problems). */
export function filterStreams(streams: ProcessStream[], text: string, which: StreamFilter = "all"): ProcessStream[] {
  const q = text.trim().toLowerCase();
  return streams.filter((s) => {
    if (which === "bfd" && !s.on_bfd) return false;
    if (which === "problems" && streamStatus(s) === "ok" && s.links.every((l) => l.resolved)) return false;
    if (!q) return true;
    return [s.id, s.title, s.from, s.to, s.from_block ?? "", s.to_block ?? "", s.template ?? ""].some((v) =>
      v.toLowerCase().includes(q),
    );
  });
}

export const BALANCE_BADGE: Record<ProcessBalance["status"], string> = {
  ok: "pass",
  imbalance: "fail",
  "not-evaluable": "info",
  unsupported: "warning",
};

/** One-line explanation of a balance: its numbers, what fails, or what is missing. */
export function balanceDetail(b: Pick<ProcessBalance, "status" | "in_kg_h" | "out_kg_h" | "failing" | "missing">): string {
  if (b.status === "ok") return `in ${formatNumber(b.in_kg_h)} kg/h, out ${formatNumber(b.out_kg_h)} kg/h`;
  if (b.status === "imbalance") return b.failing.join("; ");
  if (b.missing.length) return `missing ${b.missing.join(", ")}`;
  return "";
}

/** The BFD connection drawing stream *id*: its own, or the aggregated one representing it. */
export function bfdConnectionOf(table: StreamTable, id: string): string | undefined {
  if (table.bfd_connections[id]?.includes(id)) return id;
  return Object.entries(table.bfd_connections).find(([, ids]) => ids.includes(id))?.[0];
}

export interface PickInfo {
  /** What the picked SVG group is in the process model. */
  kind: "connection" | "stream" | "node" | "unknown";
  id: string;
  /** The streams it represents (a BFD connection), is (a PFD stream), or touches (a node). */
  streams: ProcessStream[];
  node?: ProcessNode;
  balance?: ProcessBalance | undefined;
}

/**
 * What a click on SVG group *id* of a BFD or PFD sheet means: on a BFD a connection lists the
 * streams it represents; a stream id on a PFD gives that stream; a block, step, feed or product
 * gives its balance and the streams in and out of it.
 */
export function pickInfo(table: StreamTable, sheetKind: string | undefined, id: string): PickInfo {
  const byId = new Map(table.streams.map((s) => [s.id, s]));
  const pick = (ids: string[]) => ids.map((i) => byId.get(i)).filter((s): s is ProcessStream => !!s);
  const connection = sheetKind === "bfd" ? table.bfd_connections[id] : undefined;
  if (connection) return { kind: "connection", id, streams: pick(connection) };
  // a server without the connection map: a boundary stream is its own connection
  if (sheetKind === "bfd" && byId.get(id)?.on_bfd) return { kind: "connection", id, streams: [byId.get(id)!] };
  if (sheetKind !== "bfd" && byId.has(id)) return { kind: "stream", id, streams: [byId.get(id)!] };
  const node = table.nodes.find((n) => n.id === id);
  if (node) {
    const balance = table.balances.find((b) => b.node === id);
    let streams: ProcessStream[];
    if (balance) streams = pick([...balance.streams_in, ...balance.streams_out]);
    else {
      const end = (e: string) => e.split(".")[0];
      streams = table.streams.filter((s) => end(s.from) === id || end(s.to) === id);
    }
    if (sheetKind === "bfd") streams = streams.filter((s) => s.on_bfd);
    return { kind: "node", id, streams, node, balance };
  }
  return { kind: "unknown", id, streams: [] };
}
