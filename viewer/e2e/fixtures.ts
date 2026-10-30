/**
 * Mock answers of `cheme serve` for the end-to-end tests. The SVGs follow the structure of
 * pyDEXPI's SVG export as `cheme render` post-processes it: one `g.diagram`, the border
 * and the title block (`g.border` / `g.label`, with the XML id of their DEXPI object) and a
 * `g.representation-group` per drawn object, carrying the id of the object it represents.
 */
import type { Page, Route } from "@playwright/test";
// Real responses of cheme serve (scripts/regen-fixtures.py): the process example with a
// flowsheet edit the built sheets do not follow yet.
import validateJson from "../tests/fixtures/api/validate.json" with { type: "json" };
import impactJson from "../tests/fixtures/api/impact.json" with { type: "json" };
// The real /api/layout of the ASU example with its generated model (core's frozen fixture).
import layoutJson from "../tests/fixtures/layout-asu.json" with { type: "json" };
// Core's small cabling and HVAC test plant, and the take-offs (scripts/regen-fixtures.py).
import mepJson from "../tests/fixtures/layout-mep.json" with { type: "json" };
import mtoAsuJson from "../tests/fixtures/api/mto-asu.json" with { type: "json" };
import mtoMepJson from "../tests/fixtures/api/mto-mep.json" with { type: "json" };
import lcaAsuJson from "../tests/fixtures/api/lca-asu.json" with { type: "json" };
import lcaReadinessJson from "../tests/fixtures/api/lca-asu-readiness.json" with { type: "json" };
import datasetYamlAsu from "../tests/fixtures/api/yaml-dataset-asu.json" with { type: "json" };
// Real /api/tea answers (scripts/regen-fixtures.py): the ASU (an LCOP decision) and core's process-blocks (an NPV decision, example premises).
import teaAsuJson from "../tests/fixtures/api/tea-asu.json" with { type: "json" };
import teaBlocksJson from "../tests/fixtures/api/tea-blocks.json" with { type: "json" };
import equipmentAsuJson from "../tests/fixtures/api/equipment-estimate-asu.json" with { type: "json" };
import asuTreeJson from "../tests/fixtures/api/tree-asu.json" with { type: "json" };
// The ASU's /api/status with two sign-offs (one off main) and its review records (scripts/regen-fixtures.py).
import statusAsuJson from "../tests/fixtures/api/status-asu.json" with { type: "json" };
import reviewsAsuJson from "../tests/fixtures/api/reviews-asu.json" with { type: "json" };
// The real /api/interlocks of the ASU (two low-low level trips on P-04).
import interlocksAsuJson from "../tests/fixtures/api/interlocks-asu.json" with { type: "json" };
import controlSeparationJson from "../tests/fixtures/api/control-separation.json" with { type: "json" };
// Real /api/issues of the same example with issues: in plant.yaml (GitHub stubbed), and its 503 without a token.
import issuesSeparationJson from "../tests/fixtures/api/issues-separation.json" with { type: "json" };
import issuesUnavailableJson from "../tests/fixtures/api/issues-unavailable.json" with { type: "json" };
// `/api/yaml` of each of the ASU's datasheets, by path (scripts/regen-fixtures.py --asu-files).
import asuDatasheetsJson from "../tests/fixtures/api/datasheets-asu.json" with { type: "json" };
// The ASU's GET /api/datasheets, /api/datasheets/{tag} and .svg after `cheme datasheets fill
// --dimensions` and `drawing --write`, edited for every drawing state (scripts/regen-fixtures.py --asu-datasheets).
import datasheetIndexJson from "../tests/fixtures/api/datasheets-index-asu.json" with { type: "json" };
import datasheetDetailsJson from "../tests/fixtures/api/datasheet-details-asu.json" with { type: "json" };
import datasheetDrawingsJson from "../tests/fixtures/api/datasheet-drawings-asu.json" with { type: "json" };
import datasheetSnapshotKeysJson from "../tests/fixtures/api/datasheets-snapshot-keys.json" with { type: "json" };
import penetrationJson from "../tests/fixtures/layout-asu-penetration.json" with { type: "json" };
// Real /api/simulation answers (scripts/regen-fixtures.py): the ASU without a run; core's
// examples/process-simulation with a run (current, stale, not converged) and its stream table.
import simulationAsuJson from "../tests/fixtures/api/simulation-asu.json" with { type: "json" };
import simulationRunJson from "../tests/fixtures/api/simulation-run.json" with { type: "json" };
import simulationStaleJson from "../tests/fixtures/api/simulation-stale.json" with { type: "json" };
import simulationFailedJson from "../tests/fixtures/api/simulation-failed.json" with { type: "json" };
import streamsSimulationJson from "../tests/fixtures/api/streams-simulation.json" with { type: "json" };
// Real /api/reactions of core's examples/process-ammonia (and with an unbalanced stoichiometry), its stream table.
import reactionsJson from "../tests/fixtures/api/reactions-ammonia.json" with { type: "json" };
import reactionsUnbalancedJson from "../tests/fixtures/api/reactions-ammonia-unbalanced.json" with { type: "json" };
import streamsAmmoniaJson from "../tests/fixtures/api/streams-ammonia.json" with { type: "json" };
// Real /api/reactions of core's examples/process-shift: a power-law rate on a catalyst, a fixed bed.
import reactionsShiftJson from "../tests/fixtures/api/reactions-shift.json" with { type: "json" };
// Real catalysis answers: a CO oxidation mechanism at its reactor's outlet; the shift's kinetic data and the library.
import reactionsCooxJson from "../tests/fixtures/api/reactions-coox.json" with { type: "json" };
import kineticsShiftJson from "../tests/fixtures/api/kinetics-shift.json" with { type: "json" };
import libraryShiftJson from "../tests/fixtures/api/library-shift.json" with { type: "json" };
// Real fixed beds (pre-release viewer issue 32): the shift's R1 cooled (an interior hot spot) and not solvable; a coupled kinetic bed with its run stale.
import reactionsBedCooledJson from "../tests/fixtures/api/reactions-bed-cooled.json" with { type: "json" };
import reactionsBedFailedJson from "../tests/fixtures/api/reactions-bed-failed.json" with { type: "json" };
import reactionsBedSimJson from "../tests/fixtures/api/reactions-bed-sim.json" with { type: "json" };
import simulationBedStaleJson from "../tests/fixtures/api/simulation-bed-stale.json" with { type: "json" };

export const validation = validateJson;
export const simulationAsu = simulationAsuJson;
export const simulationRun = simulationRunJson;
export const simulationStale = simulationStaleJson;
export const simulationFailed = simulationFailedJson;
export const streamsSimulation = streamsSimulationJson;
export const reactionsAmmonia = reactionsJson;
export const reactionsUnbalanced = reactionsUnbalancedJson;
export const streamsAmmonia = streamsAmmoniaJson;
export const reactionsShift = reactionsShiftJson;
export const reactionsCoox = reactionsCooxJson;
export const kineticsShift = kineticsShiftJson;
export const libraryShift = libraryShiftJson;
export const reactionsBedCooled = reactionsBedCooledJson;
export const reactionsBedFailed = reactionsBedFailedJson;
export const reactionsBedSim = reactionsBedSimJson;
export const simulationBedStale = simulationBedStaleJson;
export const layout = layoutJson;
export const mepLayout = mepJson;
export const mtoAsu = mtoAsuJson;
export const lcaAsu = lcaAsuJson;
/** `/api/lca` of the ASU with core main (the balance of pre-release issue 174, the emission estimates of pre-release issue 176); its `lca/dataset.yaml` as `/api/yaml` serves it. */
export const lcaReadiness = lcaReadinessJson;
export const teaAsu = teaAsuJson;
export const teaBlocks = teaBlocksJson;
export const interlocksAsu = interlocksAsuJson;
/** `/api/control` of core's examples/process-separation (pre-release issue 140). */
export const controlSeparation = controlSeparationJson;
/** `/api/issues` of examples/process-separation with `issues:` (stage basic; #1-#9, #4 closed, #8 with two gates, #9 a mistyped gate:Basic). */
export const issuesSeparation = issuesSeparationJson;
/** The ASU's `cheme assess equipment --json` (core's `EquipmentEstimate.payload()`), as `/api/estimate/equipment` answers it. */
export const equipmentAsu = { ...equipmentAsuJson, rev: null };
export const mtoMep = mtoMepJson;
/** The ASU's datasheet and layout file entries (its files' text from `e2e/asuFiles.ts`). */
export const asuTree = asuTreeJson;
/** `/api/yaml` of the ASU's datasheets, served with its files. */
export const asuDatasheets = asuDatasheetsJson as Record<string, unknown>;
/** The ASU with the sleeve and finding of a copy without its casing opening AIR-2002 (the ASU declares them all). */
export const asuWithPenetration = {
  ...layoutJson,
  model: { ...layoutJson.model, penetrations: penetrationJson.model.penetrations },
  model_findings: [...layoutJson.model_findings, ...penetrationJson.model_findings],
};

/** `/api/datasheets` of the ASU (39 sheets, P-4102B without one). */
export const datasheetIndex = datasheetIndexJson;
/** `/api/datasheets/{tag}` of each of them, by tag (without `source`). */
export const datasheetDetails = datasheetDetailsJson as unknown as Record<string, { drawing: { state: string } } & Record<string, unknown>>;
/** The manifest keys `cheme export-static` writes for the datasheets. */
export const datasheetSnapshotKeys = datasheetSnapshotKeysJson as Record<string, { status: number; type: string }>;
const drawings = datasheetDrawingsJson as Record<string, { drawing: string; current: string | null; svg: string }>;

/** A recorded `/api/datasheets/{tag}.svg` (`generated`: with `generated=true`), with its headers; null when not recorded. */
export function datasheetDrawing(tag: string, generated = false): { body: string; headers: Record<string, string> } | null {
  // A current drawing's generated answer is the same SVG, only the header differs.
  const recorded = (generated ? drawings[`${tag}.generated.svg`] : undefined) ?? drawings[`${tag}.svg`];
  if (!recorded) return null;
  const meta = generated ? { drawing: "generated", current: null } : recorded;
  const headers: Record<string, string> = { "x-cheme-drawing": meta.drawing };
  if (meta.current !== null) headers["x-cheme-drawing-current"] = meta.current;
  return { body: recorded.svg, headers };
}

/** A 2D plan or section as core draws it (`/api/layout/plan.svg`, `/api/layout/section.svg`). */
export function layoutSvg(title: string): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300">
<g id="layout-drawing" class="layout-drawing">
  <rect x="10" y="10" width="380" height="280" fill="none" stroke="#000" stroke-width="0.5"/>
  <g id="K-1101" class="equipment"><rect x="120" y="100" width="60" height="40" fill="#fff" stroke="#000"/><text x="130" y="125" font-size="8">K-1101</text></g>
  <text id="drawing-title" x="20" y="285" font-size="8">${title}</text>
</g>
</svg>`;
}
export const impact = impactJson;
export const statusAsu = statusAsuJson;
/** Path -> text of the ASU's `reviews/*.md` (README.md included, as the tree has it). */
export const reviewsAsu = reviewsAsuJson as Record<string, string>;
/** `checks/status.json` with the sign-offs of {@link statusAsu}. */
export const statusFileAsu = JSON.stringify({
  stages: Object.fromEntries(Object.entries(statusAsuJson.signoffs).map(([stage, { on_default_branch: _, ...entry }]) => [stage, entry])),
  checks: [],
});

/**
 * `/api/layout/plan.svg?level=|z=a,b` and `/api/layout/section.svg?x=|y=&depth=` as core answers
 * them: 404 without a model, 400 for bad arguments (both level and z, a z that is not `a,b`,
 * neither or both of x and y), else the drawing.
 */
async function layoutDrawing(route: Route, url: URL, layout: { model?: unknown }): Promise<void> {
  const q = url.searchParams;
  const bad = (detail: string) => route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ error: detail }) });
  if (!layout.model) return route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"no layout model"}' });
  const num = (v: string | null) => v !== null && v.trim() !== "" && Number.isFinite(Number(v));
  if (url.pathname.endsWith("plan.svg")) {
    const z = q.get("z");
    if (q.get("level") && z) return bad("level and z exclude each other");
    if (z && !/^-?[\d.]+,-?[\d.]+$/.test(z)) return bad("z must be a,b");
    return route.fulfill({ status: 200, contentType: "image/svg+xml", body: layoutSvg(`Plan ${q.get("level") ?? (z ? `z=${z}` : "plot")}`) });
  }
  const x = q.get("x");
  const y = q.get("y");
  if ((x === null) === (y === null) || !num(x ?? y)) return bad("give x or y");
  if (q.has("depth") && !num(q.get("depth"))) return bad("depth must be a number");
  return route.fulfill({ status: 200, contentType: "image/svg+xml", body: layoutSvg(`Section x=${x ?? "?"} y=${y ?? "?"}`) });
}

export const SHEET = "pid/P-01.xml";
export const TITLE_BLOCK = "PlantModel1_Drawing1_Groups2";
export const METADATA = "PlantMetaData1";

function sheetSvg(date: string): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="420.0" height="297.0" viewBox="0.0 0.0 420.0 297.0">
<rect x="0" y="0" width="420" height="297" fill="#f0f0f0"/>
<metadata>DEXPI Diagram: test</metadata>
<g id="diagram-Test" class="diagram">
  <g class="border" id="PlantModel1_Drawing1_Groups1">
    <polyline points="5,5 415,5 415,292 5,292 5,5" fill="none" stroke="#000" stroke-width="0.5"/>
  </g>
  <g class="label" id="${TITLE_BLOCK}">
    <polyline points="296,293 296,263 416,263" fill="none" stroke="#000" stroke-width="0.3"/>
    <rect x="296" y="263" width="120" height="30" fill="#ffffff" stroke="#000" stroke-width="0.3"/>
    <text x="300" y="275" font-size="4" fill="#000">P-01 Test plant</text>
    <text x="300" y="285" font-size="4" fill="#000">${date}</text>
  </g>
  <g id="Pump1" class="representation-group">
    <g class="shapeusage">
      <circle cx="100" cy="120" r="20" fill="#ffffff" stroke="#000" stroke-width="0.5"/>
    </g>
    <g class="label"><text x="92" y="150" font-size="5" fill="#000">P-101</text></g>
  </g>
  <g id="Tank1" class="representation-group">
    <rect x="220" y="60" width="60" height="120" fill="#ffffff" stroke="#000" stroke-width="0.5"/>
    <text x="235" y="195" font-size="5" fill="#000">T-101</text>
  </g>
</g>
</svg>`;
}

export const OLD_SVG = sheetSvg("2016-04-01");
export const NEW_SVG = sheetSvg("2026-10-17");

export const repo = {
  name: "Test plant",
  root_name: "plant",
  branch: "main",
  head: "0123456789abcdef0123456789abcdef01234567",
  stage: "basic",
  stages: [{ id: "basic", title: "Basic engineering" }],
  sheets: [
    { id: "P-01", file: SHEET, title: "Feed section", kind: "pid" },
    { id: "BFD", file: "process/BFD.xml", title: "Block flow diagram", kind: "bfd" },
    { id: "PFD", file: "process/PFD.xml", title: "Process flow diagram", kind: "pfd" },
  ],
  dirty: true,
  has_layout: true,
  has_lca: true,
};

/** A BFD as cheme-as-code renders it: blocks and connections are groups with their model ids. */
export const BFD_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100" width="200" height="100">
  <g id="diagram-Block flow diagram" class="diagram">
    <g id="MIX" class="representation-group"><rect x="10" y="30" width="40" height="30" fill="#fff" stroke="#000"/><text x="30" y="48">MIX</text></g>
    <g id="SEP" class="representation-group"><rect x="120" y="30" width="40" height="30" fill="#fff" stroke="#000"/><text x="140" y="48">SEP</text></g>
    <g id="S2" class="representation-group"><polyline points="50,45 120,45" fill="none" stroke="#000" stroke-width="3"/><text x="85" y="42">S2</text></g>
  </g>
</svg>`;

function value(v: number, unit: string, provenance = "given", stale = false) {
  return { value: v, unit, basis: null, provenance, source: "", stale };
}

export const streams = {
  rev: null,
  case: "design",
  cases: [
    { id: "design", description: "Design case", default: true },
    { id: "turndown", description: "60 %", default: false },
  ],
  default_case: "design",
  units: { pressure: "kPa(a)", temperature: "K", flow: "kg/h", duty: "kW", enthalpy: "kJ/kmol" },
  tolerance: { abs: 1, rel: 0.005 },
  streams: [
    {
      id: "S2",
      title: "Mixed feed",
      kind: "material",
      from: "M1.out",
      to: "C1.in",
      from_block: "MIX",
      to_block: "SEP",
      on_bfd: true,
      template: "aqueous",
      has_state: true,
      properties: {
        pressure: value(150, "kPa(a)"),
        temperature: value(350, "K", "assumed"),
        flow: value(1500, "kg/h"),
        duty: null,
      },
      composition: { basis: "mass_fraction", values: { ETOH: 0.3, H2O: 0.7 }, provenance: "given", source: "" },
      phase: null,
      calculated: { density: value(870, "kg/m3", "calculated", true) },
      stale: ["density"],
      imbalance: [],
      links: [{ target: "line", ref: "L-101", sheet: null, role: "", resolved: true, problem: null }],
    },
    {
      id: "S5",
      title: "Bottoms",
      kind: "material",
      from: "C1.bottom",
      to: "WATER.in",
      from_block: "SEP",
      to_block: "WATER",
      on_bfd: true,
      template: "aqueous",
      has_state: true,
      properties: { pressure: null, temperature: null, flow: value(700, "kg/h", "assumed"), duty: null },
      composition: null,
      phase: null,
      calculated: {},
      stale: [],
      imbalance: ["SEP"],
      links: [],
    },
  ],
  balances: [
    {
      node: "SEP",
      kind: "block",
      title: "Separation",
      status: "imbalance",
      in_kg_h: 1500,
      out_kg_h: 1600,
      missing: [],
      failing: ["mass 1500 kg/h in, 1600 kg/h out"],
      streams_in: ["S2"],
      streams_out: ["S5"],
    },
  ],
  nodes: [
    { id: "MIX", kind: "block", title: "Mixing", block: null, links: [] },
    { id: "SEP", kind: "block", title: "Separation", block: null, links: [] },
  ],
  bfd_connections: { S2: ["S2"], S5: ["S5"] },
};

export const flowsheetYaml = {
  kind: "flowsheet",
  schema: null,
  data: {
    schema: "cheme/process/v1",
    kind: "flowsheet",
    blocks: [{ id: "MIX", title: "Mixing" }, { id: "SEP", title: "Separation" }],
    streams: [{ id: "S2", from: "M1.out", to: "C1.in", state: { design: {} } }],
  },
};

const branches = [{ name: "main", head: repo.head, current: true }];

const tree = [
  { path: "pid", type: "dir", kind: "other" },
  { path: SHEET, type: "file", kind: "pid" },
  { path: "lists", type: "dir", kind: "other" },
  { path: "lists/equipment.yaml", type: "file", kind: "yaml" },
  { path: "process", type: "dir", kind: "other" },
  { path: "process/BFD.xml", type: "file", kind: "pid" },
  { path: "process/PFD.xml", type: "file", kind: "pid" },
  { path: "process/flowsheet.yaml", type: "file", kind: "yaml" },
];

export const EQUIPMENT_YAML = `# Equipment list
items:
  - tag: "P-101"   # feed pump
    type: CentrifugalPump
    dn: 80
    spare: false
    notes: |
      Duty pump # still the note
      key: not a key
  - tag: T-101
    type: Tank
    hint: "<script>alert(1)</script>"
`;

export const diff = {
  path: SHEET,
  old_rev: "HEAD",
  new_rev: "working tree",
  status: "",
  changes: [
    {
      kind: "modified",
      object_type: "PlantMetaData",
      object_id: METADATA,
      tag: null,
      // As the real /api/diff answers for an approval-date change (checked against the server).
      domain: "metadata",
      detail: "approvalDateRepresentation",
    },
  ],
  old_svg: OLD_SVG,
  new_svg: NEW_SVG,
  old_highlight: { [TITLE_BLOCK]: "modified" },
  new_highlight: { [TITLE_BLOCK]: "modified" },
  old_owner: { [METADATA]: TITLE_BLOCK },
  new_owner: { [METADATA]: TITLE_BLOCK },
  projection_diff: "",
};

function json(route: Route, body: unknown): Promise<void> {
  return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}

/** Answer every `/api/*` request of `page` from the fixtures above (the ASU's layout and take-off unless told otherwise). */
export async function mockApi(
  page: Page,
  options: {
    layout?: unknown;
    mto?: unknown;
    lca?: unknown;
    /** `/api/tea` (none: 404 and `has_tea: false`, as without estimate/tea.yaml); `teaError`: a 422 with that message. */
    tea?: unknown;
    teaError?: string;
    files?: Record<string, string>;
    /** Entries added to `/api/tree` (a test's own files; no request leaves the browser). */
    extraTree?: { path: string; type: string; kind: string }[];
    status?: unknown;
    reviews?: boolean;
    /** `/api/interlocks` (null: no control/cause-effect.yaml, so a 404 and no tree entry); `interlocksAt` per `?rev=`. */
    interlocks?: unknown;
    interlocksAt?: Record<string, unknown>;
    /** `/api/control` (and `has_control`; none: 404, as for a plant without control records or an older server). */
    control?: unknown;
    /** `/api/issues` (and `has_issues`); `"unavailable"`: `has_issues` with core's 503 (no token); none: 404 and no flag. */
    issues?: unknown;
    equipment?: unknown;
    hasLayout?: boolean;
    /** `/api/simulation` (none: 404, as without process/simulation.yaml or on an older server). */
    simulation?: unknown;
    /** `/api/reactions` (none: 404); `case` echoes the request's. */
    reactions?: unknown;
    /** `/api/kinetics` (and `has_kinetic_data`; none: 404). */
    kinetics?: unknown;
    /** `/api/library` (none: 404, as an older server answers). */
    library?: unknown;
    /** `/api/streams` instead of the test plant's (its `case` echoes the request's). */
    streams?: unknown;
    /** `/api/maturity` (none: 404, as an older server or a snapshot without it answers). */
    maturity?: unknown;
    /** Fields of `/api/repo` to override (the declared stage, ...). */
    repo?: Record<string, unknown>;
    /** Answer `/api/datasheets*` with the ASU's (and `has_datasheets: true`); else they 404 and `has_datasheets` is left out, as an older server does. */
    datasheets?: boolean;
  } = {},
): Promise<void> {
  const plantLayout = (options.layout ?? layout) as { model?: unknown };
  // The plant's own files (the ASU's datasheets, lifting study) only when given.
  const files = options.files ?? null;
  const mto = options.mto === undefined ? mtoAsu : options.mto;
  const lca = options.lca === undefined ? lcaAsuJson : options.lca;
  // `reviews: true`: the ASU's review records and checks/status.json, and its /api/status (unless `status` says otherwise; null: 404).
  const reviewFiles: Record<string, string> = options.reviews ? { ...reviewsAsu, "checks/status.json": statusFileAsu } : {};
  const reviewTree = Object.keys(reviewFiles).map((path) => ({ path, type: "file", kind: path.endsWith(".md") ? "markdown" : "json" }));
  const status = options.status !== undefined ? options.status : options.reviews ? statusAsuJson : null;
  const interlocks = options.interlocks ?? null;
  const interlocksTree = interlocks ? [{ path: "control", type: "dir", kind: "other" }, { path: "control/cause-effect.yaml", type: "file", kind: "yaml" }] : [];
  // No equipment estimate unless given (a 404, as an older server answers).
  const equipment = options.equipment ?? null;
  const simulation = (options.simulation ?? null) as Record<string, unknown> | null;
  const reactions = (options.reactions ?? null) as Record<string, unknown> | null;
  const streamTable = (options.streams ?? streams) as Record<string, unknown>;
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    const endpoint = url.pathname.replace(/^\/api\//, "");
    if (options.datasheets && (endpoint === "datasheets" || endpoint.startsWith("datasheets/"))) return datasheetRoute(route, url, endpoint);
    switch (endpoint) {
      case "repo":
        return json(route, {
          ...repo,
          ...options.repo,
          has_layout: options.hasLayout ?? repo.has_layout,
          has_lca: Boolean(lca),
          has_tea: Boolean(options.tea || options.teaError),
          has_equipment_estimate: Boolean(equipment),
          has_simulation: Boolean(simulation),
          has_reactions: Boolean(reactions),
          ...(options.kinetics ? { has_kinetic_data: true } : {}),
          ...(options.datasheets ? { has_datasheets: true } : {}),
          ...(options.control ? { has_control: true } : {}),
          ...(options.issues ? { has_issues: true } : {}),
        });
      case "branches":
        return json(route, branches);
      case "maturity":
        if (options.maturity === undefined) return route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"not found"}' });
        return json(route, options.maturity);
      case "tree":
        return json(route, [...tree, ...interlocksTree, ...(files ? asuTree : []), ...reviewTree, ...(options.extraTree ?? [])]);
      case "status":
        if (!status) return route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"not found"}' });
        return json(route, status);
      case "log":
        return json(route, []);
      case "pid.svg": {
        const body = url.searchParams.get("path")?.startsWith("process/") ? BFD_SVG : NEW_SVG;
        return route.fulfill({ status: 200, contentType: "image/svg+xml", body });
      }
      case "streams":
        return json(route, { ...streamTable, case: url.searchParams.get("case") ?? "design" });
      case "simulation":
        if (!simulation) return route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"no process/simulation.yaml at the working tree"}' });
        return json(route, { ...simulation, case: url.searchParams.get("case") ?? simulation.case });
      case "reactions":
        if (!reactions) return route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"no process/reactions.yaml at the working tree"}' });
        return json(route, { ...reactions, case: url.searchParams.get("case") ?? reactions.case });
      case "kinetics":
        if (!options.kinetics) return route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"no experiments/kinetics/*.yaml at the working tree"}' });
        return json(route, options.kinetics);
      case "library":
        if (!options.library) return route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"not found"}' });
        return json(route, options.library);
      case "yaml":
        if (url.searchParams.get("path") === "process/flowsheet.yaml") return json(route, flowsheetYaml);
        if (files && asuDatasheets[url.searchParams.get("path") ?? ""]) return json(route, asuDatasheets[url.searchParams.get("path")!]);
        if (files && url.searchParams.get("path") === "lca/dataset.yaml" && files["lca/dataset.yaml"] !== undefined) return json(route, datasetYamlAsu);
        return route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"not found"}' });
      case "diff":
        return json(route, diff);
      case "validate":
        return json(route, validation);
      case "impact":
        return json(route, impact);
      case "layout":
        return json(route, plantLayout);
      case "layout/plan.svg":
      case "layout/section.svg":
        return layoutDrawing(route, url, plantLayout);
      case "mto":
        if (!mto) return route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"no layout/plant-model.yaml at the working tree"}' });
        return json(route, mto);
      case "estimate/equipment":
        if (!equipment) return route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"nothing to estimate at the working tree"}' });
        return json(route, equipment);
      case "lca":
        if (!lca) return route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"no lca/lca.yaml at the working tree"}' });
        return json(route, lca);
      case "control":
        if (!options.control) return route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"no control records"}' });
        return json(route, options.control);
      case "issues":
        if (options.issues === "unavailable")
          return route.fulfill({ status: issuesUnavailableJson.status, contentType: "application/json", body: JSON.stringify(issuesUnavailableJson.body) });
        if (!options.issues) return route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"plant.yaml declares no issues"}' });
        return json(route, options.issues);
      case "tea":
        if (options.teaError) return route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ error: options.teaError }) });
        if (!options.tea) return route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"no estimate/tea.yaml at the working tree"}' });
        return json(route, options.tea);
      case "interlocks": {
        const at = url.searchParams.get("rev");
        const body = at ? options.interlocksAt?.[at] : interlocks;
        if (!body) return route.fulfill({ status: 404, contentType: "application/json", body: `{"error":"no control/cause-effect.yaml at ${at ?? "the working tree"}"}` });
        return json(route, body);
      }
      case "file": {
        const path = url.searchParams.get("path") ?? "";
        if (path === "lists/equipment.yaml") return route.fulfill({ status: 200, contentType: "text/plain", body: EQUIPMENT_YAML });
        const body = reviewFiles[path] ?? files?.[path];
        if (body !== undefined) return route.fulfill({ status: 200, contentType: "text/plain", body });
        return route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"not found"}' });
      }
      default:
        return route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"not mocked"}' });
    }
  });
}

/** `/api/datasheets`, `/api/datasheets/{tag}` and `/api/datasheets/{tag}.svg` as core answers them for the ASU. */
function datasheetRoute(route: Route, url: URL, endpoint: string): Promise<void> {
  const notFound = (what: string) => route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: what }) });
  if (endpoint === "datasheets") return json(route, datasheetIndex);
  const name = decodeURIComponent(endpoint.slice("datasheets/".length));
  if (name.endsWith(".svg")) {
    const tag = name.slice(0, -4);
    const detail = datasheetDetails[tag];
    if (!detail) return notFound(`no datasheet of ${tag} at working tree`);
    if (detail.drawing.state === "none") return route.fulfill({ status: 422, contentType: "application/json", body: '{"error":"does not validate"}' });
    const recorded = datasheetDrawing(tag, url.searchParams.get("generated") === "true");
    // Sheets without a recorded drawing get a plain one, with the headers their state gives.
    const body = recorded?.body ?? layoutSvg(`${tag} outline`);
    const state = detail.drawing.state;
    const headers = recorded?.headers ?? (state === "missing" ? { "x-cheme-drawing": "generated" } : { "x-cheme-drawing": "committed", "x-cheme-drawing-current": String(state === "current") });
    return route.fulfill({ status: 200, contentType: "image/svg+xml", body, headers });
  }
  const detail = datasheetDetails[name];
  return detail ? json(route, { ...detail, source: null }) : notFound(`no datasheet of ${name} at working tree`);
}
