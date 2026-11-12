/**
 * Typed client for the read-only JSON API of `cheme serve`.
 *
 * Every function builds its URL with {@link apiUrl}, so the query encoding lives in one place
 * (and is unit tested). A missing `rev` means the working tree. With {@link useSnapshot} the
 * same calls are answered from a static snapshot (`cheme export-static`) instead.
 */

import type { QueryValue, SnapshotSource } from "./dataSource";

export interface Stage {
  id: string;
  title: string;
}

export type SheetKind = "pid" | "bfd" | "pfd";

export interface Sheet {
  id: string;
  file: string;
  title: string;
  /** `bfd`/`pfd` are generated process sheets; older servers leave it out (a P&ID). */
  kind?: SheetKind;
  /** How the sheet is made: `flowsheet` (built by `cheme process build`), a generator script, or by hand (null). */
  generator?: { script: string; frame: string } | "flowsheet" | null;
  /** `planned`: listed in plant.yaml, not drawn yet (its file may not exist). Older servers leave it out. */
  status?: "planned" | "drafted";
}

export type Provenance = "given" | "assumed" | "calculated";

/** Where a value comes from, refining its provenance (core `foundation.schema_base.Origin`). */
export type ValueOrigin = "measured" | "vendor" | "literature" | "design-rule" | "estimate" | "simulated" | "correlation";

/** A value's uncertainty (core `foundation.uncertainty.Uncertainty`): gsd2 from a pedigree, or a cv or range. */
export interface ValueUncertainty {
  distribution: "lognormal" | "normal" | "triangular" | "uniform";
  pedigree: number[] | null;
  basic: number;
  cv: number | null;
  low: number | null;
  high: number | null;
  source: string;
}

export interface ProcessValue {
  value: number;
  unit: string;
  basis?: string | null;
  provenance: Provenance;
  source?: string;
  stale: boolean;
}

export interface ProcessLink {
  target: string;
  ref: string;
  sheet?: string | null;
  role?: string;
  resolved: boolean;
  problem: string | null;
}

export interface ProcessStream {
  id: string;
  title: string;
  kind: "material" | "energy" | "information";
  from: string;
  to: string;
  from_block: string | null;
  to_block: string | null;
  on_bfd: boolean;
  template: string | null;
  has_state: boolean;
  properties: Record<"pressure" | "temperature" | "flow" | "duty", ProcessValue | null>;
  composition: {
    basis: string;
    values: Record<string, number>;
    provenance: Provenance;
    source?: string;
    /** Input fingerprint of a calculated composition (null when given). */
    fingerprint?: string | null;
    uncertainty?: ValueUncertainty | null;
    origin?: ValueOrigin | null;
    /** The composition is calculated and its inputs changed since. Older servers leave it out. */
    stale?: boolean;
  } | null;
  phase: {
    value: string;
    vapor_fraction?: number | null;
    provenance: Provenance;
    source?: string;
    fingerprint?: string | null;
    stale: boolean;
  } | null;
  calculated: Record<string, ProcessValue>;
  /** Saved final-time wastewater results, never molecular mass/mole fractions. */
  wastewater?: Record<string, ProcessValue>;
  /** Names of calculated values whose inputs changed since they were calculated. */
  stale: string[];
  /** Blocks or steps whose balance fails and that this stream crosses. */
  imbalance: string[];
  links: ProcessLink[];
}

export interface ProcessBalance {
  node: string;
  kind: "block" | "step";
  title: string;
  status: "ok" | "imbalance" | "not-evaluable" | "unsupported";
  in_kg_h: number;
  out_kg_h: number;
  missing: string[];
  failing: string[];
  streams_in: string[];
  streams_out: string[];
  /** Reaction id -> extent (kmol/h) of a reactive block or step; left out when it has none. */
  extents_kmol_h?: Record<string, number>;
}

export interface ProcessNode {
  id: string;
  kind: "feed" | "product" | "block" | "step";
  title: string;
  block: string | null;
  links: ProcessLink[];
}

export interface StreamTable {
  wastewater?: {
    status: "available" | "partial" | "missing" | "failed" | "invalid";
    case: string;
    run_file: string;
    run_at: string | null;
    evidence: string | null;
    stale: boolean | null;
    changed_files: string[];
    columns: { key: string; label: string; unit: string; basis: string }[];
    findings: { file: string; rule: string; message: string; hint: string }[];
  };
  rev: string | null;
  case: string;
  cases: { id: string; description: string; default: boolean }[];
  default_case: string;
  units: Record<string, unknown>;
  /** Balance tolerance: `|in - out| <= abs + rel * max(in, out)`. */
  tolerance?: { abs: number; rel: number };
  streams: ProcessStream[];
  balances: ProcessBalance[];
  nodes: ProcessNode[];
  /** BFD connection id (its SVG group id) -> the stream ids it represents. */
  bfd_connections: Record<string, string[]>;
  /** Where `bfd_connections` comes from: the built BFD sheet (`represents:`) or the flowsheet. */
  bfd_connections_from?: "sheet" | "flowsheet";
}

export interface RepoInfo {
  name: string;
  root_name: string;
  branch: string | null;
  head: string | null;
  stage: string | null;
  stages: Stage[];
  sheets: Sheet[];
  dirty: boolean;
  /** True when the working tree has layout files (`layout/*.yaml`); older servers leave it out. */
  has_layout?: boolean;
  /** `lca/lca.yaml` exists: the LCA page has something to show (older servers leave it out). */
  has_lca?: boolean;
  /** `estimate/tea.yaml` exists: `GET /api/tea` answers (older servers leave it out). */
  has_tea?: boolean;
  /** There is an equipment list to cost (`GET /api/estimate/equipment` answers); older servers leave it out. */
  has_equipment_estimate?: boolean;
  /** `process/simulation.yaml` exists: `GET /api/simulation` answers (older servers leave it out). */
  has_simulation?: boolean;
  /** `process/reactions.yaml` exists: `GET /api/reactions` answers (older servers leave it out). */
  has_reactions?: boolean;
  /** `equipment/datasheets/<TAG>.yaml` exist: `GET /api/datasheets` answers (older servers leave it out). */
  has_datasheets?: boolean;
  /** `experiments/kinetics/*.yaml` exist: `GET /api/kinetics` answers (older servers leave it out). */
  has_kinetic_data?: boolean;
  /**
   * The plant documents its control (loops, sequences, a narrative or a control philosophy that
   * are not the empty templates of `cheme init`): `GET /api/control` answers. Older servers leave it out.
   */
  has_control?: boolean;
  /**
   * `plant.yaml` declares `issues:` (a GitHub repository and the plant's label): `GET /api/issues`
   * answers (or 503s when GitHub cannot be read). Older servers leave it out.
   */
  has_issues?: boolean;
}

export interface Branch {
  name: string;
  head: string;
  current: boolean;
}

export interface Commit {
  sha: string;
  short: string;
  author: string;
  /** ISO 8601. */
  date: string;
  subject: string;
}

export type FileKind = "pid" | "yaml" | "markdown" | "json" | "other";

export interface TreeEntry {
  path: string;
  type: "file" | "dir";
  kind: FileKind;
}

export type ChangeKind = "added" | "removed" | "modified" | "moved";
export type HighlightKind = "added" | "removed" | "modified";

export interface Change {
  kind: ChangeKind;
  object_type: string;
  object_id: string;
  tag: string | null;
  domain: string;
  detail: string;
  /** Id of the plant item the changed object belongs to (`""` when none); older servers leave it out. */
  item?: string;
}

export interface SheetDiff {
  path: string;
  old_rev: string;
  new_rev: string;
  changes: Change[];
  old_svg: string | null;
  new_svg: string | null;
  old_highlight: Record<string, HighlightKind>;
  new_highlight: Record<string, HighlightKind>;
  projection_diff: string;
  /** `added` / `removed` when the sheet exists on one side only, else `""`. */
  status?: "added" | "removed" | "";
  /** Why a side could not be drawn or compared (`""` when both could). Older servers leave it out. */
  error?: string;
  /** Each changed object id mapped to the SVG `<g id>` drawing it, per side. */
  old_owner?: Record<string, string>;
  new_owner?: Record<string, string>;
  /** The plant items `Change.item` names: id -> class and tag. */
  items?: Record<string, { class: string; tag: string }>;
}

export interface Session {
  token: string;
  header: string;
}

export type Level = "error" | "warning" | "info";

export interface Finding {
  file: string;
  level: Level;
  rule: string;
  message: string;
  line: number | null;
  ids: string[];
  hint: string;
  /** Stable id `<file>#<rule>:<subject>` (what an `accept:` entry names); older servers leave it out. */
  id?: string;
  /** What the finding is about when `ids` alone do not make `id` stable. */
  key?: string;
  /**
   * Region of a sheet, sheet mm, y down: `[x0, y0, x1, y1]`; a finding on the 3D model
   * (`model_findings`) gives site metres `[x0, y0, z0, x1, y1, z1]`.
   */
  box?: [number, number, number, number] | [number, number, number, number, number, number] | null;
  /** `X0,Y0,X1,Y1` for `cheme render --crop`. */
  crop?: string | null;
  /** Why the finding is accepted (an `accept:` entry of checks/checks.yaml), when it is. */
  accepted?: string | null;
  /** The length the finding measures (a span, a run, a distance), m, when it measures one. */
  measured?: number | null;
}

export interface ValidationReport {
  files: string[];
  /** What was compared: `sheets`, `not_loaded`, `planned`, `lists`, `cross_checks`, `skipped`. */
  compared?: Record<string, string[]>;
  findings: Finding[];
}

/**
 * `GET /api/impact` (`cheme impact --json`): artifacts whose sources changed since they were
 * reviewed or generated. Every finding is `cheme.review-needed` at level info; it means "look
 * again", not "wrong". Older servers have no such endpoint (404).
 */
export interface ImpactReport {
  commit: string | null;
  findings: Finding[];
}

/** An open review finding: its latest status (in the latest record listing it) is `open` or not in the vocabulary. */
export interface OpenReviewFinding {
  /** `<record stem>#<n>`: the record that raised it, and its number there. */
  id: string;
  /** Lower case, `""` when the table has none; `critical`, `high`, `major` block a sign-off. */
  severity: string;
  /** Repo path of the latest record that lists it (`reviews/<date>-<topic>.md`). */
  record: string;
  /** The finding cell's Markdown (rows may use `<br>` for line breaks). */
  finding: string;
}

/** One stage's entry of `checks/status.json` (`cheme check --stage S --write`). */
export interface StageSignoff {
  commit: string;
  /** ISO 8601. */
  date: string | null;
  signed_by: string | null;
  branch: string | null;
  /** Repo path of the review record the sign-off names. */
  review: string | null;
  reviewer_kind?: string | null;
  /** False when the signed-off commit is not on the default branch (not in effect); null when unknown. */
  on_default_branch: boolean | null;
}

export interface StatusGate {
  id: string;
  title: string;
  status: string;
  detail: string;
}

/**
 * `GET /api/status` (`cheme status --json`) of the working tree; the gates are not run (empty
 * lists). It ignores `rev`, and static snapshots do not hold it (404), nor do older servers.
 */
export interface PlantStatus {
  plant: { name: string; stage: string | null; stages: string[] };
  sheets: { id: string; file: string; state: string; [key: string]: unknown }[];
  process: Record<string, unknown> | null;
  next_sheet: string | null;
  validation: {
    errors: number;
    warnings: number;
    infos: number;
    by_rule: Record<string, number>;
    not_on_pid: Record<string, number>;
  };
  gates: Record<string, StatusGate[]>;
  signoffs: Record<string, StageSignoff>;
  /** A 0.3 `checks/status.json` (gates only, no sign-offs); else null. */
  legacy_status: { commit: string | null; stages: string[]; checks: number; passed: number; on_default_branch: boolean | null } | null;
  reviews: { records: number; open: OpenReviewFinding[] };
  git: {
    is_repo: boolean;
    branch: string | null;
    head: string | null;
    default_branch: string | null;
    dirty: string[];
    ahead: number | null;
    behind: number | null;
  };
}

// -- maturity (GET /api/maturity, checks/maturity.json; core: project/maturity.py) -----------------

/** One requirement of a maturity level: `pass`, `fail`, `missing` (an input is absent) or `unsupported` (core cannot evaluate it). */
export interface MaturityRequirement {
  id: string;
  title: string;
  status: "pass" | "fail" | "missing" | "unsupported" | (string & {});
  /** False: reported (and listed as a limitation) but it does not block the level. */
  required: boolean;
  /** `cheme.maturity-<requirement>`. */
  rule: string;
  /** Repo path ("" when none); a directory ends in `/`. */
  file: string;
  line: number | null;
  detail: string;
  hint: string;
  evidence: Record<string, unknown>;
}

/** One of the four cumulative levels; `reached` only when it and every level below pass. */
export interface MaturityLevel {
  id: string;
  title: string;
  /** The highest process-library manifest `maturity` label the level supports. */
  library_maturity: string;
  /** `not-evaluated`: above the report's `evaluated_through`, no requirements. */
  status: "pass" | "fail" | "not-evaluated" | (string & {});
  reached: boolean;
  requirements: MaturityRequirement[];
}

export interface MaturityModelBasis {
  id: string;
  role: string;
  basis: string;
  predictive: boolean;
  sourced: boolean;
  simulated: boolean;
  file: string;
  line: number | null;
  detail: string;
  sources: unknown[];
  assumptions: string[];
  limitations: string[];
  evidence: unknown[];
}

export interface MaturityLimitation {
  subject: string;
  file: string;
  line: number | null;
  limitation: string;
}

/**
 * `cheme maturity --json` (schema `cheme/maturity-report/v1`): `GET /api/maturity` of the
 * working tree, a static snapshot's copy of it, or `checks/maturity.json` as `--write` left it.
 * Calculation maturity (`levels`, `level`) is kept apart from artifact completeness
 * (`artifacts`) and independent review (`review`), which never raise a level.
 */
export interface MaturityReport {
  schema: string;
  kind: string;
  core_version: string;
  /** ISO 8601 (UTC); null in a static snapshot (deterministic). */
  checked_at: string | null;
  /** The highest level reached; null: none. */
  level: string | null;
  level_index: number;
  evaluated_through: string;
  library_maturity: string | null;
  levels: MaturityLevel[];
  model_basis: MaturityModelBasis[];
  cases: { id: string; description: string; default: boolean; balanced: boolean; simulated: boolean }[];
  assumptions: { design_basis: string[]; assumed_values: Record<string, number>; models: Record<string, string[]> };
  unresolved: { requirement: string; status: string; file: string; detail: string }[];
  limitations: MaturityLimitation[];
  artifacts: {
    note: string;
    sheets: { id: string; kind: string; file: string; exists: boolean; generated: boolean; fingerprint: string | null }[];
    files: Record<string, string[]>;
    boundary?: Record<string, unknown>;
  };
  review: {
    note: string;
    manifest_status: string | null;
    records: { path: string; topic: string | null; reviewer_kind: string | null; reviewed_commit: string | null; approved_by: string | null }[];
  };
  manifest: {
    file: string | null;
    supported_maturity: string | null;
    claimed_maturity?: unknown;
    review_status?: unknown;
    /** null: undecided (a level above `evaluated_through` might support the claim). */
    claim_exceeds_evidence?: boolean | null;
  };
  /** The input files as they were when the report was computed: HEAD, the inputs with uncommitted changes and each input's `sha256:` fingerprint. */
  source: { commit: string | null; dirty: string[]; fingerprints: Record<string, string> };
  findings: { file: string; line: number | null; level: Level; rule: string; message: string; hint: string }[];
}

// -- datasheets (GET /api/datasheets, core: project/datasheets.py `datasheet_report`) -----------

/** The state of a datasheet's outline drawing `equipment/datasheets/<TAG>.svg`; `none`: the datasheet does not validate. */
export type DrawingState = "current" | "stale" | "missing" | "none";

/** One datasheet of `GET /api/datasheets` (core's `DatasheetEntry.summary()`). */
export interface DatasheetSummary {
  tag: string;
  file: string;
  /** The file validates against the datasheet schema. */
  valid: boolean;
  type: string | null;
  service: string;
  /** null when the file does not validate. */
  draft: boolean | null;
  /** Fields marked assumed, and the open ones (core's `field_counts`, every section). */
  counts: { assumed: number; tbd: number; supplier: number; not_applicable: number };
  nozzles: number;
  has_dimensions: boolean;
  has_weights: boolean;
  /** Repo path of its outline drawing (`equipment/datasheets/<TAG>.svg`), whether or not it exists. */
  drawing: string;
  /** The drawing file exists (current or stale). */
  has_drawing: boolean;
  /** The drawing file is what `cheme datasheets drawing` writes for the datasheet now. */
  drawing_current: boolean;
  /** Findings on the datasheet and its drawing, by level. */
  findings: { error: number; warning: number; info: number };
}

/** `GET /api/datasheets?rev=`: every datasheet, and the equipment-list items without one; 404 when there are none (or an older server). */
export interface DatasheetIndex {
  rev: string | null;
  directory: string;
  datasheets: DatasheetSummary[];
  /** Tags of the equipment list without a datasheet. */
  missing: string[];
  source?: unknown;
}

/** `GET /api/datasheets/{tag}?rev=`: one datasheet; a 404 for an unknown tag (or an older server). */
export interface DatasheetDetail {
  rev: string | null;
  tag: string;
  file: string;
  summary: DatasheetSummary;
  /** The parsed datasheet (defaults filled in); null when the file does not validate. */
  datasheet: Record<string, unknown> | null;
  /** The file as data (its YAML as JSON); null when it does not parse. */
  data: unknown;
  drawing: { file: string; state: DrawingState; current: boolean };
  /** Schema, markers, against the equipment list, the layout model, the P&IDs and the line list, drawing drift. */
  findings: Finding[];
  source?: unknown;
}

/** `GET /api/datasheets/{tag}.svg`: the SVG and what the server says it is (headers; a snapshot has none). */
export interface DatasheetDrawing {
  svg: string;
  /** `X-Cheme-Drawing`: the committed file, or generated from the datasheet; null when not told (a snapshot). */
  kind: "committed" | "generated" | null;
  /** `X-Cheme-Drawing-Current` of a committed drawing; null when not told. */
  current: boolean | null;
}

// -- simulation (GET /api/simulation, core: domains/process/simulation/record.py) ----------------

/** A spec value of `process/simulation.yaml`: a quantity with its provenance (`unit` left out: the flowsheet's). */
export interface SimSpecQuantity {
  value: number;
  unit?: string;
  provenance: "given" | "assumed" | "calculated";
  source?: string;
}

/** One step's (or block's) spec: quantities, plain values (`stages: 3`) and nested maps (`side_draws`, `condenser_spec`). */
export type SimUnitSpec = Record<string, unknown>;

/** A value the run gave a stream: a quantity, or the composition by basis. */
export type SimStreamValue = { value: number; unit: string } | { basis: string; values: Record<string, number> };

export interface SimRunStream {
  id: string;
  /** Field (`temperature`, `pressure`, `flow`, `duty`, `composition`) -> the simulated value. */
  values: Record<string, SimStreamValue>;
  /** The fields of the flowsheet that hold the simulated value (written by this run, or already current). */
  filled: string[];
  /** Field -> provenance of a value `--fill` leaves alone (given or assumed in the flowsheet). */
  kept: Record<string, string>;
}

export interface SimRunUnit {
  id: string;
  /** The simulator's unit type (`compressor`, `cooler`, `distillation_column`); left out of an excluded unit. */
  unit?: string | null;
  status: "simulated" | "excluded";
  /** True, false, or null when the run did not converge and no message names the unit (unknown). */
  converged?: boolean | null;
  /** Result key (`duty_kW`) -> value. */
  results?: Record<string, number>;
  messages?: string[];
  warnings?: string[];
  /** Why an excluded unit is left out. */
  reason?: string;
  /** How the unit's outlet follows from its inlets. Older servers leave it out. */
  basis?: "predictive" | "shortcut" | "specified";
  /** A kinetic reactor coupled as an external unit: `external-unit`. */
  coupling?: string;
  /** Its outer loop around the DWSIM solves. */
  outer_loop?: { iterations?: number; max_iterations?: number; converged?: boolean };
}

/** One case's entry of `process/simulation-run.json` (`cheme process simulate --fill`). */
export interface SimulationRun {
  case: string;
  /** ISO 8601, UTC. */
  run_at: string;
  /** `cheme-as-code <version>`. */
  tool: string;
  /** `method`: the property method the simulator ran with (older servers leave it out). */
  simulator: { name: string; version: string | null; method?: string };
  property_package: string | null;
  /** The fingerprint every simulated stream value carries. */
  model_fingerprint: string;
  /** The inputs as they were after the run: HEAD, the files changed against it, each input file's fingerprint. */
  inputs: { commit: string | null; dirty: string[]; fingerprints: Record<string, string> };
  converged: boolean;
  /** `converged` / `not-converged`. Older servers leave it out. */
  status?: "converged" | "not-converged";
  /** Null where the simulator does not report it. */
  iterations: number | null;
  messages: string[];
  units: SimRunUnit[];
  /** Empty when the run did not converge (no stream value is written). */
  streams: SimRunStream[];
  findings: Finding[];
  /** The run's energy closure (reference state, tolerance, per unit and for the plant); null when it
   * did not converge. Not shown by the viewer yet. Older servers leave it out. */
  energy?: Record<string, unknown> | null;
}

export type SimUnitStatus = "simulated" | "excluded" | "refused" | "not-simulated" | "unknown";

/** One step or block as the simulation sees it: its status now, its spec and its row of the recorded run. */
export interface SimulationUnit {
  id: string;
  unit: string | null;
  status: SimUnitStatus;
  /** Why it is excluded, refused or not simulated ("" when simulated). */
  reason: string;
  spec: SimUnitSpec | null;
  run: SimRunUnit | null;
  /** How the unit's outlet follows from its inlets. Older servers leave it out. */
  basis?: "predictive" | "shortcut" | "specified";
}

/** `GET /api/simulation?case=&rev=`: 404 without `process/simulation.yaml`, 422 when it does not load or the case is unknown. */
export interface SimulationView {
  rev: string | null;
  /** `process/simulation.yaml`. */
  file: string;
  /** `process/simulation-run.json`. */
  run_file: string;
  case: string | null;
  cases: string[];
  spec: {
    simulator: string;
    property_package: string | null;
    components: Record<string, string>;
    tolerance: Record<string, number>;
    tear_streams: string[];
    exclude: string[];
    guesses: Record<string, unknown>;
    specs: Record<string, SimUnitSpec>;
  };
  /** The recorded run of the case; null when none is recorded. */
  run: SimulationRun | null;
  /** Null without a run (or when the flowsheet does not load), else whether the inputs changed since it. */
  stale: boolean | null;
  staleness: { model_fingerprint: string | null; current_fingerprint: string | null; changed_files: string[] };
  units: SimulationUnit[];
  /** Why the flowsheet does not load (the spec and the record are still shown); null when it does. */
  problem: string | null;
  findings: Finding[];
}

// -- reactions (GET /api/reactions, core: domains/process/reaction_view.py) ----------------------

export interface ReactionConversion {
  key: string;
  value: number;
  provenance: "given" | "assumed";
  source: string;
}

export interface ReactionHeat {
  /** Per kmol of extent of the reaction as written: negative when exothermic. */
  value: number;
  unit: string;
  /** K. */
  temperature: number;
  provenance: "given" | "assumed" | "calculated";
  source: string;
}

/** `ln K = a + b / T + c ln T + d T` (T in K), K on partial pressures in bar. */
export interface ReactionEquilibriumConstant {
  a: number;
  b: number;
  c: number;
  d: number;
  temperature_range: [number, number] | null;
  provenance: "given" | "assumed";
  source: string;
}

/** A block or step the reaction takes place in. */
export interface ReactionPlace {
  unit: string;
  kind: string | null;
  /** `conversion` or `equilibrium`; null when the item does not say. */
  model: string | null;
  /** Equilibrium temperature approach, K. */
  approach_K: number;
  /** The conversion it uses, and where it is given (`flowsheet <id>` or `process/reactions.yaml`). */
  conversion: { value: number; from: string } | null;
}

/** `k = A (T/T_ref)^n exp(-Ea / (R T))`, in the rate law's units (core: `domains/chemistry/rates.py`). */
export interface RateArrhenius {
  /** At T_ref, in the units of `rate_law.k_unit`. */
  A: number;
  /** kJ/kmol (numerically J/mol). */
  Ea: number;
  n: number;
  /** K. */
  T_ref: number;
}

/** One term of an LHHW denominator: `K = A exp(-dH / (R T))` times its components' driving forces to their exponents. */
export interface RateAdsorption {
  A: number;
  /** kJ/kmol; negative: adsorption is exothermic. */
  dH: number;
  exponents: Record<string, number>;
}

/** A reaction's rate law as `process/reactions.yaml` declares it (power law or LHHW). */
export interface RateLaw {
  form: "power_law" | "lhhw";
  /** catalyst_mass: kmol/(kg_cat s); volume: kmol/(m3 s). */
  basis: "catalyst_mass" | "volume";
  /** partial_pressure: bar; concentration: kmol/m3. */
  driving: "partial_pressure" | "concentration";
  k: RateArrhenius;
  /** Component id -> its exponent in the forward term. */
  orders: Record<string, number>;
  /** equilibrium: times (1 - Q/K). */
  reverse: "none" | "equilibrium";
  adsorption: RateAdsorption[];
  /** LHHW: the denominator's exponent. */
  power: number;
  /** The catalyst it holds for (an id of `process/catalysts.yaml`), or "". */
  catalyst: string;
  /** K, min and max. */
  temperature_range: [number, number] | null;
  provenance: Provenance;
  source: string;
}

/** What core derives from a rate law (`reaction_view.rate_law_view`). */
export interface RateLawView {
  /** `r = k(T) · p_CO · p_CO2^-0.36 · (1 - Q/K)`. */
  expression: string;
  k_expression: string;
  rate_unit: string;
  driving_unit: string;
  /** The units of A (and k). */
  k_unit: string;
  catalyst: string | null;
  /** k(T) over the rate's temperature range, else its catalyst's window; empty with neither. */
  k_profile: { temperature_K: number; k: number }[];
  k_profile_from: "temperature_range" | "catalyst window" | null;
}

/** A microkinetic mechanism (elementary surface steps), once core's reaction schema has one: shown as its steps. */
export interface ReactionMechanism {
  site_density: number;
  adsorbates: string[];
  steps: { id: string; equation?: string; stoichiometry: Record<string, number>; reverse?: unknown; energies?: unknown }[];
  catalyst?: string;
  provenance: Provenance;
  source?: string;
}

export interface Reaction {
  id: string;
  title: string;
  equation: string;
  /** The reaction SMILES derived from the components' SMILES (null when one is missing). Older servers leave it out. */
  reaction_smiles?: string | null;
  stoichiometry: Record<string, number>;
  phase: "vapor" | "liquid" | "mixed" | null;
  reversible: boolean;
  conversion: ReactionConversion | null;
  heat_of_reaction: ReactionHeat | null;
  equilibrium_constant: ReactionEquilibriumConstant | null;
  /** Its rate law (power law or LHHW, core's `domains/chemistry/rates.py`); null without one. */
  rate: RateLaw | null;
  /** The expression, units and k(T) of `rate`; null without one. */
  rate_law: RateLawView | null;
  /** Its elementary steps, when core's schema gives them (microkinetics). */
  mechanism?: ReactionMechanism | null;
  /** The mechanism analysed at its reactor's outlet; null without a mechanism (older servers leave it out). */
  microkinetics?: Microkinetics | null;
  /** The catalyst: text, or the id of an entry of `process/catalysts.yaml`. */
  catalyst: string;
  sources: string[];
  key_component: string | null;
  /** The model of the units it runs in: one of them, `mixed`, or null when none says. */
  type: string | null;
  units: ReactionPlace[];
  /** `change`: element -> atoms created (positive) or lost, empty when balanced or not evaluable. */
  element_balance: { evaluable: boolean; balanced: boolean | null; change: Record<string, number> };
}

/**
 * A mechanism's mean-field steady state (`cheme chemistry microkinetics --json`) at the outlet of
 * the first reactor running it (core: `reaction_view.microkinetics_view`): `missing` says why
 * there is none (the analysis fields are then left out).
 */
export interface Microkinetics {
  /** Where it is evaluated: the reactor, its outlet stream, T and the mechanism's gas partial pressures; null when no reactor gives them. */
  conditions: { unit: string; stream: string; temperature_K: number; pressures_bar: Record<string, number> } | null;
  missing: string | null;
  /** The product the TOF counts. */
  product?: string;
  /** Turnover frequency, 1/s (per site). */
  tof_per_s?: number;
  /** Adsorbate (and `*`, the free sites) -> fraction of the sites. */
  coverages?: Record<string, number>;
  step_rates_per_s?: Record<string, number>;
  /** Campbell's degree of rate control per step (they sum to 1). */
  rate_control?: Record<string, number>;
  apparent_activation_kJ_kmol?: number;
  /** Apparent reaction orders in the gas species. */
  orders?: Record<string, number>;
  mechanism_source?: string;
  mechanism_provenance?: Provenance;
}

/** A solved fixed bed (`reactor: pfr`, core: `domains/process/fixed_bed.py`). */
export interface ReactorBed {
  catalyst_mass_kg: number;
  catalyst_volume_m3: number;
  outlet_temperature_K: number;
  outlet_pressure_kPa: number;
  pressure_drop_kPa: number;
  /** The highest temperature along the bed, over every integration step (core reports no position). */
  hot_spot_K: number;
  /** Along the bed, by catalyst mass from the inlet: the inlet, then evenly spaced points to the outlet (the solver's own values there). */
  profile: { catalyst_mass_kg: number; temperature_K: number; pressure_kPa: number }[];
  /** What core did not calculate (no pressure drop, ...) and what it found (the rate range left, a limiting transport). */
  notes: string[];
  /** Weisz-Prater and Mears per reaction at the inlet and the outlet; empty without the particle data (left out by older servers). */
  transport?: Record<string, unknown>;
}

/** A row of `cheme process reactors --json`. */
export interface ReactorRow {
  node: string;
  /** The solved bed of a fixed-bed reactor; null for the other models (or when it cannot be solved: `missing` says why, `the bed: ...`). Left out by a core before beds. */
  bed: ReactorBed | null;
  kind: string;
  model: string | null;
  /** The balance status of the node (`ok`, `imbalance`, ...). */
  balance: string;
  streams_in: string[];
  streams_out: string[];
  temperature_out_K: number | null;
  pressure_out_kPa: number | null;
  approach_K: number;
  /** The gas model of its equilibrium (older servers leave it out: ideal). */
  fugacity?: "ideal" | "peng_robinson";
  reactions: {
    id: string;
    extent_kmol_h: number | null;
    heat_of_reaction_kJ_kmol: number | null;
    ln_k: number | null;
    /** ln(Q/K) at the outlet: 0 at equilibrium, negative short of it. */
    ln_q_over_k: number | null;
    /** The rate at the outlet where the reaction has a rate law (else null), in `rate_unit`. */
    rate: number | null;
    rate_unit: string | null;
  }[];
  duty_kW: number | null;
  /** The assumptions behind `duty_kW`, and its basis (`ideal gas`, ...). Older servers leave them out. */
  duty_assumptions?: string[];
  duty_basis?: string;
  /** The solved stirred tank of a batch or CSTR reactor; null for the other models. Not shown by
   * the viewer yet. Older servers leave it out. */
  tank?: Record<string, unknown> | null;
  /** What it lacks to give a duty or an approach. */
  missing: string[];
}

/** `GET /api/reactions?case=&rev=`: 404 without `process/reactions.yaml` (or the flowsheet), 422 when it does not load or the case is unknown. */
export interface ReactionsView {
  rev: string | null;
  file: string;
  case: string;
  cases: string[];
  reactions: Reaction[];
  reactors: ReactorRow[];
  /** The balances of the reactive blocks and steps (`cheme validate`'s, without a title) and the findings on reactions, reactors and those balances. */
  balance: { balances: (Omit<ProcessBalance, "title"> & { title?: string })[]; findings: Finding[] };
  /** The catalysts (null from an older core). */
  kinetics: ReactionsKinetics | null;
}

/** Data of a catalyst carry their provenance. */
interface CatalystProvenanced {
  provenance: Provenance;
  source: string;
}

/** A catalyst of `process/catalysts.yaml` (core: `domains/chemistry/catalysts.py`). */
export interface Catalyst {
  id: string;
  name: string;
  active_phase: string;
  promoters: string[];
  support: string;
  /** SI units: m, kg/m3, m2/g. */
  physical:
    | (CatalystProvenanced & {
        form: string | null;
        particle_diameter: number | null;
        sphericity: number | null;
        particle_density: number | null;
        bulk_density: number | null;
        bed_voidage: number | null;
        surface_area: number | null;
      })
    | null;
  /** K and kPa(a), min and max. */
  window: (CatalystProvenanced & { temperature: [number, number] | null; pressure: [number, number] | null }) | null;
  space_velocity: (CatalystProvenanced & { basis: "GHSV" | "WHSV" | "LHSV"; range: [number, number]; gas?: "wet" | "dry" }) | null;
  poisons: string[];
  deactivation: (CatalystProvenanced & { lifetime: number | null; mechanisms: string[]; regeneration: string }) | null;
  price: (CatalystProvenanced & { value: number; unit: string; year: number }) | null;
  sources: string[];
}

/** A block or step holding a catalyst, with its declared bed. */
export interface CatalystUnit {
  unit: string;
  kind: string | null;
  reactor: string | null;
  reactions: string[];
  /** As the flowsheet declares it (catalyst_mass, volume, diameter, length, tubes, heat, ...). */
  bed: (Record<string, unknown> & { provenance?: Provenance; source?: string }) | null;
}

export interface CatalystEntry extends Catalyst {
  /** The reactions it catalyses (their `catalyst` or their rate's). */
  reactions: string[];
  units: CatalystUnit[];
}

/** `kinetics` of `/api/reactions`: `process/catalysts.yaml` (file null without it) and its findings. */
export interface ReactionsKinetics {
  file: string | null;
  catalysts: CatalystEntry[];
  findings: Finding[];
}

// -- kinetic data (GET /api/kinetics, core: project/kinetics.py) -----------------------------------

/** A file of `experiments/kinetics/` (schema `cheme/kinetic-data/v1`). */
export interface KineticData {
  reaction: string;
  catalyst?: string;
  basis: "catalyst_mass" | "volume";
  /** T in K, partial pressures in bar, the rate in kmol/(kg s) or kmol/(m3 s). */
  points: { temperature: number; partial_pressures: Record<string, number>; rate: number }[];
  provenance: Provenance;
  source?: string;
}

/** A fitted parameter (`ln_A`, `Ea`, `order_<species>`) with its standard error and 95 % interval. */
export interface FitParameter {
  value: number;
  standard_error: number | null;
  interval_95: [number, number] | null;
}

/** The default fit of a kinetic data file (`cheme experiments fit-rate --json`). */
export interface KineticFit {
  /** The fitted law, as `process/reactions.yaml` would hold it. */
  rate: RateLaw;
  parameters: Record<string, FitParameter>;
  /** Of ln r. */
  r_squared: number;
  points: number;
  /** ln r measured - ln r fitted, per point. */
  residuals: number[];
  notes: string[];
  /** Fitted over 1 - Q/K (the reaction is reversible and its K known). */
  reverse: boolean;
}

export interface KineticDataFile {
  file: string;
  /** Null when the file does not validate. */
  data: KineticData | null;
  fit: KineticFit | null;
  problem: string | null;
}

/** `GET /api/kinetics?rev=`: 404 without data files (or process files). */
export interface KineticsView {
  rev: string | null;
  directory: string;
  files: KineticDataFile[];
}

// -- reaction library (GET /api/library, core: domains/process/reaction_library.py) --------------

/** An entry of the reaction library (`cheme chemistry library`), each item `in_plant` when the plant has it. */
export interface LibraryEntry {
  id: string;
  title: string;
  /** K and kPa(a). */
  window: { temperature: [number, number] | null; pressure: [number, number] | null };
  /** Which reactor model the entry's own data supports. Older servers leave it out. */
  model_basis?: {
    kind: "stoichiometry_only" | "conversion_selectivity" | "equilibrium" | "kinetic";
    provenance?: "given" | "assumed" | null;
    note: string;
  };
  /** `in_plant`: the plant's id of the component with this CAS number, else null. */
  components: { id: string; name: string; cas: string; formula: string; in_plant: string | null }[];
  /** `in_plant`: the plant has this id with the same stoichiometry. */
  reactions: { id: string; equation: string; reversible: boolean; phase: string | null; catalyst: string | null; heat_of_reaction: ReactionHeat | null; in_plant: boolean }[];
  catalysts: {
    id: string;
    name: string;
    active_phase: string;
    promoters: string[];
    support: string;
    window: { temperature: [number, number] | null; pressure: [number, number] | null; provenance: Provenance; source: string } | null;
    poisons: string[];
    in_plant: boolean;
    /** The plant's catalyst of this id has other data (`--add` refuses it); older servers leave it out. */
    differs?: boolean;
  }[];
  sources: string[];
}

/** `GET /api/library?rev=`. */
export interface LibraryView {
  rev: string | null;
  entries: LibraryEntry[];
}

export type CheckState = "pass" | "fail" | "n/a";

export interface CheckStatus {
  id: string;
  title: string;
  stage: string;
  status: CheckState | string;
  detail: string;
}

export interface ChecksReport {
  checks: CheckStatus[];
}

/** A JSON Schema, only the parts the viewer reads. */
export interface JsonSchema {
  type?: string | string[];
  title?: string;
  description?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  anyOf?: JsonSchema[];
  oneOf?: JsonSchema[];
  allOf?: JsonSchema[];
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  definitions?: Record<string, JsonSchema>;
  enum?: unknown[];
  default?: unknown;
  [key: string]: unknown;
}

export interface YamlDoc {
  data: unknown;
  kind: string | null;
  schema: JsonSchema | null;
}

/** Site frame: metres, x east, y north, z up, origin at the south-west corner of the site. */
export type XY = [number, number];
export type XYZ = [number, number, number];

export interface LayoutSite {
  width: number;
  depth: number;
  name?: string | null;
}

export type AreaKind = "process" | "utilities" | "storage" | "road" | "reserved" | "building";

export interface LayoutArea {
  id: string;
  title?: string | null;
  /** `[x0, y0, x1, y1]`. */
  box: [number, number, number, number];
  kind?: AreaKind | string | null;
  /** Named by a clash finding (only `road` areas can be). */
  clash?: boolean;
}

export interface LayoutRoad {
  id: string;
  title?: string | null;
  points: XY[];
  width?: number | null;
  clash?: boolean;
}

export interface LayoutRack {
  id: string;
  title?: string | null;
  points: XY[];
  width?: number | null;
  /** Elevations of the rack levels (beams). */
  levels?: number[] | null;
  clash?: boolean;
}

export type BuildingLevelKind = "floor" | "platform" | "roof";

export interface BuildingLevel {
  id: string;
  title?: string | null;
  elevation: number;
  height?: number | null;
  kind?: BuildingLevelKind | string | null;
  /** The height cheme-as-code checks against: `height`, else up to the next level, else a default. */
  clear_height?: number | null;
}

export interface LayoutBuilding {
  id: string;
  title?: string | null;
  /** South-west corner of the unrotated footprint; `rotation_deg` turns the footprint about it. */
  origin: XY;
  /** Along the building's local x (east at rotation 0). */
  width: number;
  /** Along the building's local y (north at rotation 0). */
  depth: number;
  rotation_deg?: number | null;
  levels?: BuildingLevel[] | null;
  /** Column grid, offsets from `origin` along the local axes. */
  frame?: { grid_x?: number[] | null; grid_y?: number[] | null } | null;
  /** `[x0, y0, x1, y1]` in the site frame. */
  footprint?: [number, number, number, number] | null;
  /** Bottom and top elevation cheme-as-code uses for clashes. */
  heights?: [number, number] | null;
  /** What the building is for (the building spacing table's key). */
  use?: string | null;
  clash?: boolean;
}

export type EquipmentShape = "box" | "vertical_cylinder" | "horizontal_cylinder" | "sphere";

export type EquipmentSize =
  | [number, number, number]
  | { diameter?: number | null; height?: number | null; length?: number | null };

export interface PlacedEquipment {
  tag: string;
  /** Equipment type from the equipment list. */
  type?: string | null;
  /** Plan centre `[x, y]` and bottom elevation `z`. */
  position: XYZ;
  shape: EquipmentShape | string;
  size: EquipmentSize;
  rotation_deg?: number | null;
  building?: string | null;
  level?: string | null;
  /** P&ID sheet id the equipment is drawn on (from the equipment list). */
  sheet?: string | null;
  /** Repo path of that sheet's DEXPI file, resolved by cheme-as-code. */
  sheet_file?: string | null;
  /** Service from the equipment list. */
  service?: string | null;
  /** `[x0, y0, z0, x1, y1, z1]`: the box cheme-as-code checks clashes with. */
  bbox?: [number, number, number, number, number, number] | null;
  /** Named by a clash finding. */
  clash?: boolean;
  /** Notes of the placement, e.g. `ASSUMED - ...`. */
  notes?: string | null;
  /** Shape family of the generated model (`vessel`, `pump`, ...); older servers leave it out. */
  family?: string | null;
  /** Where the size comes from: `list`, `placement` or `default`. */
  size_from?: "list" | "placement" | "default" | string | null;
  /** `{building | structure, level}` the item stands on. */
  mount?: Record<string, string> | null;
}

/** The route check of one line of `piping/line-list.yaml` (`GET /api/layout` `lines`). */
export interface LineRoute {
  number: string;
  from: string;
  to: string;
  /** Plan positions of the two ends, when both are placed. */
  from_point: XY | null;
  to_point: XY | null;
  /** Straight plan distance between the ends, m. */
  distance: number | null;
  /** Length estimate along the pipe racks, m, when the line is carried on racks. */
  length_est: number | null;
  racks: string[];
  /** Rule of the finding on this line, if any. */
  finding: string | null;
}

/** Where an object of the generated model comes from. */
export type ModelSource = "generated" | "pinned" | "declared";

/** What a model object refers to (any subset). */
export interface ModelRefs {
  tag?: string | null;
  /** DEXPI id on the sheet. */
  dexpi?: string | null;
  /** Sheet file, e.g. `pid/P-01.xml`. */
  sheet?: string | null;
  /** Input file that declares it. */
  file?: string | null;
  lines?: string[] | null;
  /** DEXPI segment ids. */
  segments?: string[] | null;
}

/** Fields every object of the model has. */
export interface ModelObject {
  id: string;
  refs: ModelRefs;
  source: ModelSource | string;
}

export type ModelPartKind = "cylinder" | "cone" | "cap" | "box" | "sphere" | "member" | "annulus" | "torus" | "frustum";
/** A part's rendering hint; `cage` (a ladder cage) is drawn as wire. */
export type PartMaterial =
  | "shell"
  | "steel"
  | "casing"
  | "motor"
  | "plates"
  | "fan"
  | "grating"
  | "handrail"
  | "cage"
  | "cladding"
  | "fire_wall"
  | "concrete"
  | "painted"
  | "stainless"
  | "galvanised"
  | "insulation_jacket"
  | "guard"
  | "flange"
  | "opening"
  | "insulation"
  | "instrument"
  | "valve"
  | "handwheel"
  | "actuator"
  | "roof"
  | "door"
  | "glass"
  | "louvre"
  | "crane"
  | "tray_power"
  | "tray_instrument"
  | "junction_box"
  | "ahu"
  | "duct_supply"
  | "duct_extract"
  | "duct_outdoor"
  | "duct_exhaust"
  | "grille_supply"
  | "grille_extract";

/**
 * A solid of an item, frame, platform, rack or building, site frame: `cylinder` (start, end,
 * radius), `cone` (start, end, radius at the start, radius_end), `cap` (half ellipsoid: centre of
 * its base, outward unit axis, radius, depth), `box` (centre, size in the item's frame,
 * rotation_deg about z), `sphere` (centre, radius), `member` (a steel section from start to end,
 * `profile` [b, h], `section`) and `annulus` (a ring sector: `centre` of its top, inner `radius`,
 * outer `radius_end`, `depth` down from the top, `arc_deg` [from, to] ccw from east, all round
 * without; `to` < `from` wraps through east), `torus` (a ring of a round tube: `centre`, unit
 * `axis` normal to its plane, `radius` to the tube's centre line, `tube` (the tube's radius),
 * a sector from unit `ref` over `arc_deg`) and `frustum` (a rectangular one, upright: `centre` of
 * its bottom face, `size` [dx, dy, height], `size_end` [dx, dy] of the top, `rotation_deg`).
 */
export interface ModelPart extends ModelObject {
  kind: ModelPartKind | string;
  /** Rendering hint. */
  material: PartMaterial | string;
  /** Level of detail: absent at every distance, 1 the envelope (from afar only), 2 detail (close up only). */
  lod?: number | null;
  /** Torus: radius of the tube. */
  tube?: number | null;
  /** Torus: unit direction (in its plane) where `arc_deg` starts. */
  ref?: XYZ | null;
  /** Frustum: [dx, dy] of the top face. */
  size_end?: [number, number] | number[] | null;
  start?: XYZ | null;
  end?: XYZ | null;
  radius?: number | null;
  radius_end?: number | null;
  centre?: XYZ | null;
  axis?: XYZ | null;
  depth?: number | null;
  /** Box: [dx, dy, dz]; frustum: [dx, dy, height] of the bottom face. */
  size?: XYZ | [number, number] | number[] | null;
  rotation_deg?: number | null;
  /** Member section `[b, h]`, m. */
  profile?: [number, number] | null;
  /** Section name, e.g. `HEB300` (ASSUMED by span). */
  section?: string | null;
  arc_deg?: [number, number] | null;
}

export interface ModelNozzle extends ModelObject {
  /** SubTagName on the P&ID (N1), else its DEXPI id. */
  name: string;
  dn?: number | null;
  /** Where the pipe connects: the face of the nozzle's flange (on the shell in a model without levels of detail). */
  point: XYZ;
  /** Where the neck leaves the shell (absent on a machine's own flange). */
  base?: XYZ | null;
  /** Outward unit vector. */
  direction: XYZ;
  basis: "pid" | "default" | "override" | string;
  side?: "top" | "bottom" | "left" | "right" | string | null;
  /** A declared remote mount of its transmitter (`piping/routing.yaml` `operators:`, `TAG/NOZZLE`). */
  operator?: ModelOperator | null;
}

/**
 * How a valve or transmitter out of reach is operated, as declared in `piping/routing.yaml`
 * `operators:`: `chainwheel`, `extension_spindle`, `remote_operator` or, for an instrument,
 * `remote_mount`. The rules on the model check it; the model draws no chain, spindle or stand.
 */
export interface ModelOperator {
  kind: "chainwheel" | "extension_spindle" | "remote_operator" | "remote_mount" | string;
  /** `infrequent` or `regular` (a chain wheel needs infrequent). */
  use?: string | null;
  /** A remote mount's `impulse` lines (the default) or `capillary`. */
  via?: string | null;
  /** Declared length of the spindle, operator or lines, m (else to the nearest floor). */
  length_m?: number | null;
  /** Why (a DESIGN.md decision). */
  basis?: string | null;
}

/** A box to keep free (bundle pull, motor removal, access). */
export interface ModelEnvelope extends ModelObject {
  kind: "bundle_pull" | "motor_removal" | "access" | string;
  centre: XYZ;
  size: XYZ;
  rotation_deg: number;
}

export interface ModelEquipment extends ModelObject {
  tag: string;
  type?: string | null;
  family: string;
  shape: EquipmentShape | string;
  size_from: "list" | "placement" | "default" | string;
  /** The sizes used, m (`head` and `support` are words). */
  dimensions: Record<string, number | string>;
  position: XYZ;
  rotation_deg: number;
  /** `{building | structure, level}` the item stands on. */
  mount?: Record<string, string> | null;
  /** Height of the concrete plinth it stands on, m (placement `plinth:`; its bottom is on it). */
  plinth?: number | null;
  bbox: [number, number, number, number, number, number];
  parts: ModelPart[];
  nozzles: ModelNozzle[];
  envelopes: ModelEnvelope[];
}

export interface ModelSite extends ModelObject {
  name?: string;
  width: number;
  depth: number;
}

export interface ModelArea extends ModelObject {
  title?: string;
  box: [number, number, number, number];
  kind: string;
  /** A bund's wall height, m. */
  wall_height?: number | null;
  /** A bund's concrete walls (`<area>/wall-<side>`). */
  parts?: ModelPart[] | null;
}

export interface ModelRoad extends ModelObject {
  title?: string;
  points: XY[];
  width: number;
}

export interface ModelRack extends ModelObject {
  title?: string;
  points: XY[];
  width: number;
  levels: number[];
  /** Generated steel: a bent every few metres (`member` columns and a beam per tier). */
  parts: ModelPart[];
  /** Caged access ladders at its ends (declared, or proposed to review). */
  ladders?: ModelLadder[] | null;
  /** The declared steel between the bents (`{spacing_m, levels?, section?}`; drawn in `parts`). */
  intermediate_supports?: { spacing_m: number; levels?: number[] | null; section?: string | null } | null;
  /** The rack's own bent spacing as declared, m (absent: the routing rule's). */
  bent_spacing_m?: number | null;
}

export interface ModelLevel {
  id: string;
  title?: string;
  elevation: number;
  height: number;
  clear_height: number;
  kind: string;
}

export interface ModelBuilding extends ModelObject {
  title?: string;
  origin: XY;
  width: number;
  depth: number;
  rotation_deg: number;
  footprint: [number, number, number, number];
  heights: [number, number];
  levels: ModelLevel[];
  frame?: { grid_x?: number[] | null; grid_y?: number[] | null } | null;
  /** An overhead crane (`{capacity_t, rail_elevation?, notes}` from `layout/building.yaml`). */
  crane?: { capacity_t?: number | null; rail_elevation?: number | null; notes?: string | null } | null;
  /** What the building is for (the building spacing table's key: control, substation, process, ...). */
  use?: string | null;
  /** Clad sides (own frame): `all`, `none` or a list of `north`, `south`, `east`, `west`. */
  walls: "all" | "none" | string[];
  wall_material: string;
  openings: BuildingOpening[];
  /** Generated `box` wall panels (`<building>/wall-<side>-<k>`) cut around the openings. */
  parts: ModelPart[];
}

/** A door, roller door, louvre, window or (a casing's) hatch in a wall. */
export interface BuildingOpening {
  id?: string | null;
  /** `north`, `east`, `south`, `west`; `roof` only on a penetration (a roof opening cannot be declared). */
  side: string;
  /** Along the side from its left end seen from outside, m; on the roof along the owner's x from its origin corner. */
  offset: number;
  /** Along the side (on the roof along the owner's x), m. */
  width: number;
  /** Vertical (on the roof along the owner's y), m. */
  height: number;
  /** Above grade, m; on the roof along the owner's y from its origin corner. */
  sill?: number;
  kind?: string;
}

/** A pipe class from `piping/pipe-specs.yaml`: its code, material and rendering colour. */
export interface PipeClass {
  code: string;
  material?: string | null;
  colour?: string | null;
}

/** A routed DEXPI segment: the polyline of the pipe's axis, its sizes and how it was routed. */
export interface ModelPipe extends ModelObject {
  /** Line number. */
  line: string;
  /** DEXPI segment id. */
  segment: string;
  /** Segment number on its line (`S2`). */
  segment_number?: string | null;
  /** Polyline of the axis, site frame (orthogonal except pinned and skewed-rack runs). */
  points: XYZ[];
  dn: number;
  /** Outside diameter, m. */
  od: number;
  /** Insulation thickness, mm (0: bare). */
  insulation_mm: number;
  /** The line's pipe class (`piping/pipe-specs.yaml`, else the line's pressure class code). */
  class?: PipeClass | null;
  fluid?: string | null;
  /** Length along the route, m. */
  length: number;
  /** How it was routed: `astar`, `astar_coarse`, `rack` (`rack+...` when a leg fell back), `via`, `open`, `direct`, `pinned`. */
  method: string;
  racks?: string[] | null;
  /** Rack tier elevation, m. */
  tier?: number | null;
  /** Ends left open (a vent or relief outlet). */
  open_ends?: ("start" | "end")[] | null;
  /** What the start and the end connect to: `nozzle`, `junction`, `open`, `item`, `battery_limit`, `line` (with its `ref`). */
  ends?: { kind: string; ref?: string | null }[] | null;
  /** A `direct` route over the obstacles: a fallback to review. */
  review_needed?: boolean | null;
  /** Why the router took this route (`rack: across areas`, `local: short run`, `open end`). */
  reason?: string | null;
  /** Generated detail along the pipe (flanges, shoes, guides), when core provides it. */
  parts?: ModelPart[] | null;
  /** Cladding of an insulated pipe: `cold` (vapour-tight), `hot` or `personnel` (protection). */
  jacket?: string | null;
}

/** A pipe shoe or guide where a pipe rests on a steel member (detail parts only). */
export interface ModelSupport extends ModelObject {
  kind: "shoe" | "guide" | string;
  /** Id of its pipe. */
  pipe: string;
  /** Part id of the member it rests on. */
  on: string;
  point: XYZ;
  parts: ModelPart[];
}

/** Support steel under a pipe: a T-post, post or stub, declared (any id, older ones
 * `<pipe>/post-<k>`) or proposed (`<pipe>/SP-<arc>`, the arc its place along the pipe in m). */
export interface ModelSupportSteel extends ModelObject {
  kind: "t_post" | "post" | "stub" | string;
  at: XY;
  /** Top of steel, m. */
  top: number;
  /** Its foot, m (0: grade). */
  base: number;
  width: number;
  rotation_deg: number;
  /** Pipe ids it carries. */
  serves?: string[] | null;
  review_needed?: boolean | null;
  reason?: string | null;
  parts: ModelPart[];
}

/** A proposed step-over where a low pipe crosses a walkway. */
export interface ModelStepOver extends ModelObject {
  pipe: string;
  walkway: string;
  point: XYZ;
  /** Deck height above the floor, m. */
  height: number;
  box: [number, number, number, number, number, number];
  review_needed: boolean;
  parts: ModelPart[];
}

/** A valve, instrument, reducer, silencer or other item placed along a pipe route. */
export interface ModelInlineItem extends ModelObject {
  /** `valve`, `check_valve`, `safety_valve`, `reducer`, `silencer`, `filter`, `instrument`, `item`. */
  kind: string;
  /** DEXPI class. */
  dexpi_class: string;
  tag?: string | null;
  /** On the pipe's axis, site frame. */
  point: XYZ;
  /** Unit vector along the pipe. */
  direction: XYZ;
  line: string;
  segment: string;
  /** Id of its pipe. */
  pipe: string;
  /** Its body, operator and flanges as parts, when core provides them (drawn instead of the viewer's own shape). */
  parts?: ModelPart[] | null;
  /** The operator declared for it in `piping/routing.yaml` `operators:` (by its tag or id). */
  operator?: ModelOperator | null;
}

/** A stair of a structure: switchback flights outside `side`, as stringers, treads and landings. */
export interface ModelStair extends ModelObject {
  /** Level ids (`grade` for the ground). */
  from: string;
  to: string;
  side: string;
  width: number;
  flights: number;
  box: [number, number, number, number, number, number];
  parts: ModelPart[];
  offset?: number | null;
  /** How far out from the side its inner edge stands, m (declared; default outside the enclosure wall). */
  out?: number | null;
  /** A generated proposal to review, and why. */
  review_needed?: boolean | null;
  reason?: string | null;
}

/** A ladder from `base` to `top`: rails, and a `cage` cylinder when the rise exceeds 3 m. */
export interface ModelLadder extends ModelObject {
  base: XYZ;
  top: XYZ;
  cage: boolean;
  parts: ModelPart[];
  /** Level ids it joins, where it stands and which way it faces (structure ladders). */
  from?: string | null;
  to?: string | null;
  at?: number[] | null;
  facing?: string | null;
  /** A rack ladder's end: `start` or `end`. */
  end?: string | null;
  /** A generated proposal to review, and why. */
  review_needed?: boolean | null;
  reason?: string | null;
}

/** An access platform around a vertical item, with its ladder. */
export interface ModelPlatform extends ModelObject {
  tag: string;
  kind: "circular" | "rectangular" | string;
  /** Floor elevation above grade, m. */
  elevation: number;
  /** Floor elevation above the item's bottom, m. */
  item_elevation: number;
  width: number;
  arc_deg?: [number, number] | null;
  /** A generated proposal to review before it is pinned or declared. */
  review_needed?: boolean | null;
  /** Nozzle and valve ids it reaches. */
  serves?: string[] | null;
  parts: ModelPart[];
  ladder: ModelLadder;
}

export interface StructureLevel {
  id: string;
  title?: string | null;
  elevation: number;
  kind: "deck" | "platform" | string;
  /** Plan extent of a platform level `[x0, y0, x1, y1]` (absent: the whole frame). */
  extent?: [number, number, number, number] | null;
  /** `regular` (a deck's default) or `occasional` (a platform's). */
  use?: string | null;
}

/** A steel frame of `layout/structures.yaml`. */
export interface ModelStructure extends ModelObject {
  title?: string | null;
  origin: XY;
  rotation_deg: number;
  width: number;
  depth: number;
  footprint: [number, number, number, number];
  height: number;
  grid_x: number[];
  grid_y: number[];
  levels: StructureLevel[];
  /** Section names used (`column`, `beam`, `brace`), `assumed` when by span. */
  sections: Record<string, string | boolean>;
  /** Columns, beams, bracing, handrails and gratings. */
  parts: ModelPart[];
  stairs: ModelStair[];
  ladders: ModelLadder[];
  /** Enclosure walls: `box` parts (`<id>/wall-<side>[-<k>]`, cut around the openings). */
  walls: ModelPart[];
  /** The enclosure's declared openings (absent without any). */
  openings?: BuildingOpening[] | null;
  /** A valve access platform: the in-line valves it is for. */
  serves?: string[] | null;
  /** A proposed structure (a valve access platform, `source: generated`). */
  review_needed?: boolean | null;
  reason?: string | null;
}

/** A pipe through a building's wall or roof or a structure's enclosure outside the declared openings. */
export interface ModelPenetration extends ModelObject {
  /** The building or structure. */
  owner: string;
  /** Part id of the wall panel (a building's `<id>/roof` for its roof slab). */
  wall: string;
  /** Id of the pipe. */
  pipe: string;
  /** Where the pipe's axis meets the wall. */
  point: XYZ;
  /** The wall's material (`cladding`, `fire_wall`, `casing`). */
  material: string;
  /** The pipe has an end inside the owner (else it passes through). */
  end_inside: boolean;
  /** How far the axis runs in the wall's plane, m. */
  length: number;
  /** The opening that would take it, in the owner's frame (`side: roof`: its plan frame). */
  opening: BuildingOpening;
  review_needed: boolean;
  reason: string;
}

/** A rack's tray tier: steel of its own above the top pipe tier. */
export interface ModelTrayTier extends ModelObject {
  rack: string;
  elevation: number;
  parts: ModelPart[];
}

/** A cable tray: `points` its bottom centreline, a `box` part per straight run. */
export interface ModelTray extends ModelObject {
  system: "power" | "instrument" | string;
  /** `trunk` (along a rack), `room` (from its room), `link` (across rack joints), `branch` (to a load). */
  kind: "trunk" | "room" | "link" | "branch" | string;
  points: XYZ[];
  /** A branch ending at its motor's `cable_entry` beside the item: the terminal box its cable drops to (cable, not tray). */
  drop_to?: XYZ | null;
  width: number;
  depth: number;
  length: number;
  /** Tags of the cables it carries. */
  cables: string[];
  fill: number;
  fill_max: number;
  rack?: string | null;
  method?: string | null;
  review_needed?: boolean | null;
  parts: ModelPart[];
}

/** A junction box for field instrument cables (declared, or proposed per area). */
export interface ModelJunctionBox extends ModelObject {
  tag: string;
  point: XYZ;
  area?: string | null;
  instruments: string[];
  room?: string | null;
  review_needed?: boolean | null;
  parts: ModelPart[];
}

/** A cable of the cable schedule: from its room (or instrument) to its load (or junction box). */
export interface ModelCable extends ModelObject {
  tag: string;
  system: "power" | "instrument" | string;
  /** `motor`, `feeder`, `field` (instrument to junction box), `multipair` (junction box to the control room). */
  kind: "motor" | "feeder" | "field" | "multipair" | string;
  from: string;
  to: string;
  from_point: XYZ;
  to_point: XYZ;
  size: string;
  od_mm: number;
  count: number;
  voltage_v?: number | null;
  power_kw?: number | null;
  current_a?: number | null;
  pairs?: number | null;
  /** Tray ids in order from its room. */
  trays: string[];
  route_length: number;
  /** With terminations and slack, m. */
  length: number;
  basis?: string | null;
  review_needed?: boolean | null;
  reason?: string | null;
}

/** The cabling summary of the model. */
export interface ModelCabling {
  cables: number;
  power: number;
  instrument: number;
  motors: number;
  motors_skipped: number;
  instruments: number;
  junction_boxes: number;
  trays: number;
  tray_length_m: number;
  cable_length_m: number;
  /** Tray rules in force: numbers, and `avoid_zones` (zone kinds a tray keeps out of). */
  rules: Record<string, number | string[]>;
  missing: { tag: string; kind: string; reason: string }[];
}

/** An air handling unit of `layout/hvac.yaml`. */
export interface ModelHvacUnit extends ModelObject {
  title?: string | null;
  building: string;
  level?: string | null;
  /** Centre of its base. */
  position: XYZ;
  /** [length, width, height], m. */
  size: XYZ;
  rotation_deg: number;
  capacity_m3h?: number | null;
  supply_m3h: number;
  extract_m3h: number;
  intake?: string | null;
  exhaust?: string | null;
  /** Top of each port: `outdoor`, `exhaust`, `return`, `supply`. */
  ports: Record<string, XYZ>;
  parts: ModelPart[];
}

/** A supply or extract terminal (a grille) of a ventilated room. */
export interface ModelHvacTerminal {
  id: string;
  system: "supply" | "extract" | string;
  point: XYZ;
  flow_m3h: number;
  source: ModelSource | string;
  parts: ModelPart[];
}

/** A ventilated room and its terminals. */
export interface ModelHvacRoom extends ModelObject {
  title?: string | null;
  building: string;
  level?: string | null;
  unit: string;
  extent: [number, number, number, number];
  floor: number;
  height: number;
  volume_m3: number;
  air_changes_per_h: number;
  supply_m3h: number;
  extract_m3h: number;
  basis?: string | null;
  terminals: ModelHvacTerminal[];
}

/** An HVAC duct: one piece of constant air flow, a `box` part per straight run. */
export interface ModelDuct extends ModelObject {
  system: "supply" | "extract" | "outdoor" | "exhaust" | string;
  kind: "main" | "header" | "intake" | "exhaust" | string;
  unit: string;
  room?: string | null;
  serves?: string[] | null;
  points: XYZ[];
  /** Across, horizontal, m. */
  width: number;
  height: number;
  flow_m3h: number;
  velocity_m_s: number;
  velocity_max_m_s: number;
  length: number;
  method?: string | null;
  review_needed?: boolean | null;
  reason?: string | null;
  parts: ModelPart[];
}

/** The HVAC summary of the model. */
export interface ModelHvac {
  units: number;
  rooms: number;
  terminals: number;
  ducts: number;
  supply_m3h: number;
  extract_m3h: number;
  duct_length_m: number;
  duct_area_m2: number;
  louvres: {
    building: string;
    opening: string;
    kind: string;
    flow_m3h: number;
    free_area_m2: number;
    units: string[];
    velocity_m_s: number;
    velocity_max_m_s: number;
  }[];
  rules: Record<string, unknown>;
  missing: { tag: string; kind: string; reason: string; level?: string }[];
}

/** A hazardous, oxygen, keep-clear, maintenance or escape zone and its volumes. */
export interface ModelZone extends ModelObject {
  kind: string;
  title?: string | null;
  /** Hazardous area zone number (0, 1, 2, 20, 21, 22). */
  zone?: number | string | null;
  basis?: string | null;
  /** Its explicit volumes and those around its release points. */
  volumes: ZoneVolume[];
}

/** One volume of a zone (explicit, or from a release point and the radius table). */
export interface ZoneVolume {
  shape: "box" | "cylinder" | "sphere" | string;
  source: ModelSource | string;
  /** `[x0, y0, z0, x1, y1, z1]` of a box. */
  box?: [number, number, number, number, number, number] | null;
  /** Centre of a sphere, or of a cylinder's base. */
  centre?: XYZ | null;
  radius?: number | null;
  height?: number | null;
  zone?: number | string | null;
  /** The release point: a tag, `TAG/N1` or a line number. */
  item?: string | null;
  source_kind?: string | null;
  release_grade?: string | null;
  substance_class?: string | null;
  basis?: string | null;
  status?: string | null;
}

/** A segment the router could not route, and why. */
export interface ModelUnrouted {
  line: string;
  segment: string;
  segment_number?: string | null;
  sheet: string;
  reason: string;
}

/** How full a rack tier is: the width its lanes take. */
export interface RackFill {
  rack: string;
  tier: number;
  used_m: number;
  width_m: number;
  /** used_m / width_m. */
  fill: number;
}

/** The router's summary. */
export interface ModelRouting {
  segments: number;
  routed: number;
  unrouted: number;
  /** Routes by method (a chain counts once). */
  methods: Record<string, number>;
  /** Routes by the router's reason (a pipe's `reason`). */
  reasons?: Record<string, number> | null;
  /** Segments that end at a battery limit, by how (`battery limit rule`). */
  battery_limits?: Record<string, number> | null;
  rack_fill: RackFill[];
}

export interface ModelProvenance {
  generator: string;
  generator_version: string;
  generator_sha256: string;
  sources: Record<string, string>;
  output_sha256: string;
}

/** `layout/plant-model.yaml` (kind `layout_model`, schema `cheme/layout_model/v1`), the generated 3D model. */
export interface LayoutModel {
  schema: string;
  kind: "layout_model" | string;
  provenance: ModelProvenance;
  units: "m" | string;
  site: ModelSite | null;
  areas: ModelArea[];
  roads: ModelRoad[];
  racks: ModelRack[];
  buildings: ModelBuilding[];
  equipment: ModelEquipment[];
  pipes: ModelPipe[];
  structures: ModelStructure[];
  zones: ModelZone[];
  platforms: ModelPlatform[];
  inline: ModelInlineItem[];
  unrouted: ModelUnrouted[];
  routing: ModelRouting;
  /** Pipe shoes and guides on the steel. */
  supports?: ModelSupport[] | null;
  /** Step-overs proposed where a low pipe crosses a walkway. */
  step_overs?: ModelStepOver[] | null;
  /** Posts and T-posts under pipes (declared in layout/structures.yaml, or proposed). */
  support_steel?: ModelSupportSteel[] | null;
  /** Pipes through walls outside the declared openings. */
  penetrations?: ModelPenetration[] | null;
  // Only with an electrical list:
  tray_tiers?: ModelTrayTier[] | null;
  trays?: ModelTray[] | null;
  junction_boxes?: ModelJunctionBox[] | null;
  /** The cable schedule. */
  cables?: ModelCable[] | null;
  cabling?: ModelCabling | null;
  // Only with `layout/hvac.yaml`:
  hvac_units?: ModelHvacUnit[] | null;
  hvac_rooms?: ModelHvacRoom[] | null;
  ducts?: ModelDuct[] | null;
  hvac?: ModelHvac | null;
}

/** A minimum horizontal distance between two things of the plot plan (`site-plan.yaml`). */
export interface Separation {
  from: string;
  to: string;
  min_m?: number | null;
  min_factor_of_height?: number | null;
  height_of?: "max" | "from" | "to" | string;
  measure?: "footprint" | "centre" | string;
  reason?: string;
  basis?: string;
}

export interface Layout {
  rev?: string | null;
  files?: Record<string, string>;
  notes?: string[];
  site: LayoutSite | null;
  areas: LayoutArea[];
  roads: LayoutRoad[];
  racks: LayoutRack[];
  buildings: LayoutBuilding[];
  equipment: PlacedEquipment[];
  /** Line routes; older servers leave it out. */
  lines?: LineRoute[];
  findings: Finding[];
  /** The site plan's separations as written; older servers leave it out. */
  separations?: Separation[];
  /** The committed generated model (`layout/plant-model.yaml`), null when there is none. */
  model?: LayoutModel | null;
  /** `model.zones` (empty without a model). */
  zones?: ModelZone[];
  /** The rules on the model (clashes, headroom, access, ...), with a 3D `box`. */
  model_findings?: Finding[];
}

/** One row of the material take-off: a category, item, DN, class, spec and group, summed. */
export interface MtoRow {
  /** `pipe`, `elbow`, `tee`, `reducer`, `flange`, `gasket`, `valve`, `inline`, `steel`, `grating`, `insulation`, `concrete`. */
  category: string;
  item: string;
  dn: number | null;
  dn2: number | null;
  class: string;
  spec: string;
  group: string;
  count: number;
  quantity: number;
  unit: string;
  length_m: number | null;
  /** The row's key, e.g. `pipe DN100 PN16 bare`. */
  key: string;
}

/** One line of the estimate: a priced take-off row or a factor. */
export interface EstimateLine {
  /** `material`, `direct`, `indirect`, `contingency`. */
  section: string;
  id: string;
  description: string;
  /** A row's quantity, or a factor's base cost. */
  quantity: number;
  unit: string;
  rate: number | null;
  /** The rate's or factor's id. */
  basis: string;
  cost: number | null;
  status: string;
  source: string;
  year: number | null;
}

/** The estimate of the take-off with `estimate/rates.yaml` (factor method). */
export interface Estimate {
  currency: string;
  cost_year: number | null;
  /** Example rates: the estimate prices nothing real. */
  example: boolean;
  model_sha256: string | null;
  totals: { materials?: number; direct?: number; indirect?: number; contingency?: number; total?: number; unpriced_rows?: number };
  lines: EstimateLine[];
  findings: Finding[];
}

/** `GET /api/mto`: the take-off of the committed model, and its estimate when there are rates. */
export interface MtoReport {
  rev: string | null;
  model: string;
  model_sha256: string | null;
  columns: string[];
  rows: MtoRow[];
  /** Per category, quantity per unit. */
  totals: Record<string, Record<string, number>>;
  findings: Finding[];
  estimate: Estimate | null;
}

/** One item of the equipment estimate (core's `CostLine`, one per equipment-list item). */
export interface EquipmentCostLine {
  tag: string;
  /** The item's DEXPI class, e.g. `CentrifugalPump`. */
  type: string;
  /** The correlation of the package data (`pump_centrifugal`, `hx_fixed_tube`, `tower`, ...), null when none fits. */
  correlation: string | null;
  /** The correlation's attribute A (volume, area, power, flow, duty), null when unknown. */
  size: number | null;
  unit: string;
  /** Where the size comes from: the project, a datasheet key (with its own source, `ASSUMED`, `draft`) or the list's dimensions. */
  size_source: string;
  /** Purchased cost at the base cost index (CEPCI 397, 2001), US dollars. */
  cp0_base: number | null;
  fp: number | null;
  fm: number | null;
  fbm: number | null;
  cbm_base: number | null;
  /** The project's cost index over the base one. */
  index_ratio: number | null;
  /** Escalated purchased cost. */
  purchased: number | null;
  /** Escalated bare module cost (installation and indirects included), null when a factor is missing. */
  bare_module: number | null;
  /** `bare module`, `purchased only`, `not covered`, `project cost` or `excluded: <reason>`. */
  status: string;
  notes: string;
}

/** An item's own cost from `estimate/cost-basis.yaml` (a quotation), in its own currency and year. */
export interface EquipmentOwnCost {
  tag: string;
  cost: number;
  currency: string;
  year: number;
  status: string;
  source: string;
}

/**
 * `GET /api/estimate/equipment` (`cheme assess equipment --json`): the equipment estimate from
 * published cost correlations (Turton et al., CAPCOST), escalated by the project's cost index.
 */
export interface EquipmentEstimate {
  rev?: string | null;
  currency: string;
  /** The correlations' base cost index. */
  base: { cepci: number; year: number };
  /** The project's cost index (`cost_index` of `estimate/cost-basis.yaml`), null without one (costs stay at the base year). */
  index: { value: number; year: number; month?: string; source?: string } | null;
  /** AACE International 18R-97 class, 5 (screening) to 1. */
  estimate_class: number;
  /** The expected accuracy range of the class: the low and high ends, each as a range (`-20 % to -50 %`). */
  accuracy: { low: string; high: string };
  totals: {
    purchased: number;
    bare_module: number;
    items: number;
    bare_module_items?: number;
    purchased_only?: number;
    own_cost?: number;
    excluded?: number;
    not_covered: number;
  };
  lines: EquipmentCostLine[];
  own_costs: EquipmentOwnCost[];
  findings: Finding[];
  source?: { commit?: string | null; dirty?: string[]; fingerprints?: Record<string, string> } | null;
}

/** One foreground flow of the LCA inventory, per functional unit. */
export interface LcaInventoryRow {
  /** `feed:<id>`, `product:<id>`, `emission:<component>` or `construction:<id>`. */
  key: string;
  title: string;
  /** `input` or `output`. */
  direction: string;
  /** `material`, `energy`, `emission` or `construction`. */
  kind: string;
  /** The plant's amount before allocation: per hour (operation) or in total (construction). */
  plant: number;
  plant_unit: string;
  /** Per functional unit (allocated; a co-product: what is made with one functional unit). */
  quantity: number;
  unit: string;
  /** `given`, `calculated` or `assumed`. */
  provenance: string;
  streams: string[];
  /** `coproduct`, `emission`, `free`, `factor:<id>`, `activity:<name>`, ... or empty (unmapped). */
  mapping: string;
  /** `operation` or `construction`. */
  phase: string;
}

/** An impact category: its id, title, unit and method. */
export interface LcaCategory {
  id: string;
  title: string;
  unit: string;
  method: string;
}

/** One contribution: an inventory row's impact in one category and scenario, per functional unit. */
export interface LcaImpact {
  category: string;
  key: string;
  /** The factor id or Brightway activity it is characterised with. */
  basis: string;
  quantity: number;
  unit: string;
  /** Impact per unit of the row. */
  factor: number;
  value: number;
  status: string;
  source: string;
  year: number | null;
  /** `baseline` or a scenario id. */
  scenario: string;
  phase: string;
  /** Its source registry entries, comma-joined (`method:ipcc2021`, `brightway:<project>`); older servers leave it out. */
  source_id?: string;
  /** The geographies it represents, comma-joined. */
  location?: string;
}

/** An exchange whose burden in a category is unknown: excluded from the totals, never counted as 0. */
export interface LcaGap {
  category: string;
  key: string;
  /** `unmapped`, `missing`, `factor-category`, `dataset-unlinked`, ...; `elementary-uncharacterised` and `biosphere-uncharacterised` are outside the method (no gap). */
  reason: string;
  /** Per functional unit; null when the amount itself is unknown (`no-weight`, `unmatched`). */
  quantity: number | null;
  unit: string;
  phase: string;
  scenario: string;
  detail: string;
}

/** A source registry entry the results draw on (lca/factors.yaml `sources:`). */
export interface LcaSource {
  id: string;
  title: string;
  provider: string;
  version: string;
  url: string;
  licence: string;
  attribution: string;
  /** `public`, `restricted` or `local`. */
  publication: string;
  redistribution: boolean;
  geography: string;
  year: number | null;
  method: string;
}

/** `GET /api/lca`: `cheme assess lca --json` of a revision, without the source. */
export interface LcaReport {
  rev: string | null;
  case: string;
  /** e.g. `1 t GOXP`. */
  functional_unit: string;
  boundary: string;
  allocation: {
    method: string;
    shares: Record<string, number>;
    /** Every allocation method (baseline; several products only): older servers leave it out. */
    comparison?: LcaAllocationMethod[];
  };
  /** The factors are an example: the results characterise nothing real. */
  example_factors: boolean;
  /** `factors` or `brightway`, and what it read. */
  backend: string;
  background: string;
  inventory: LcaInventoryRow[];
  categories: LcaCategory[];
  /** Baseline total per category id. */
  totals: Record<string, number>;
  /** The scenario ids in order, `baseline` first (older servers leave it out). */
  scenario_ids?: string[];
  /** Total per category id of each scenario (use `scenario_ids` for the order: ids like 2030 reorder object keys). */
  scenarios: Record<string, Record<string, number>>;
  impacts: LcaImpact[];
  findings: Finding[];
  /** The Monte Carlo of the baseline, when lca/lca.yaml asks for one (older servers: absent). */
  uncertainty?: LcaUncertainty | null;
  /** How far the result can be read: `complete`, `screening`, `partial` or `unavailable` (older servers: absent). */
  classification?: string;
  /** e.g. `partial screening carbon footprint`. */
  label?: string;
  reasons?: string[];
  /** Every category is a climate one: a carbon footprint, not a multi-impact LCA. */
  climate_only?: boolean;
  /** What the declared boundary leaves out. */
  limitations?: string[];
  sources?: LcaSource[];
  /** Every scenario's gaps, and the flows outside a method's scope. */
  gaps?: LcaGap[];
  /** Totals that do not stand (older servers: absent): per scenario and category, the
   * exchanges the baseline characterises that are gaps there, or null when every contribution is
   * a gap. */
  not_comparable?: Record<string, Record<string, string[] | null>>;
  /** Core's comparison verdict of each scenario against the baseline (older servers:
   * absent): `like-for-like`, `proxy`, `not comparable` or `baseline`, with the reasons. */
  comparability?: Record<string, { verdict: string; reasons: string[]; compared?: unknown[] }>;
  /** What each scenario is (older servers: absent): the geography and year of its
   * background (applicability, not a plant site), its electricity procurement, and its own
   * flowsheet case when it changes the foreground. */
  scenario_details?: {
    id: string;
    title: string;
    location: string;
    year: number | null;
    electricity: string | null;
    case: string | null;
    source: string;
  }[];
  /** The most restrictive policy of the sources, whether the results may be published, and which sources restrict them. */
  publication?: { policy: string; publishable: boolean; restricted_by: string[] };
  /** The data quality rating of the plant's dataset; null when no exchange is rated, absent from older servers. */
  data_quality?: LcaDataQuality | null;
  /** The water of the plant's dataset, m3 per its basis; null without a water flow, absent from older servers. */
  water?: LcaWater | null;
  /** The mass, element, carbon-origin and energy balance of the plant's dataset (as `lca/manifest.json` `balance`); absent from older servers. */
  balance?: LcaBalance | null;
}

/** `data_quality` of `/api/lca` (core `quality.Rating`): the TfS DQR and its indicators, 1 (best) to 5. */
export interface LcaDataQuality {
  TeR: number;
  GeR: number;
  TiR: number;
  /** (TeR + GeR + TiR) / 3. */
  dqr: number;
  /** PEF-style precision and completeness, and their DQR. */
  P: number;
  C: number;
  dqr_pef: number;
  /** Measured data's share, 0 to 1. */
  primary_share: number;
  /** Weighted by the exchanges' contributions to `basis` (a category id), else the unweighted mean. */
  weighted: boolean;
  basis: string;
  /** The worst of TeR, GeR and TiR. */
  weakest: string;
  exchanges: number;
}

/** `water` of `/api/lca` (core `elementary.water_balance`). */
export interface LcaWater {
  basis: string;
  unit: string;
  withdrawal: number;
  returned: number;
  evaporated: number;
  consumption: number;
}

/** One quantity's balance (kg, or kg C), per the dataset's basis. */
export interface LcaClosure {
  in: number;
  out: number;
  /** In minus out. */
  residual: number;
  /** The residual relative to the larger side. */
  relative: number;
  /** Within the tolerance. */
  closed: boolean;
}

/** `balance` of `/api/lca` and `lca/manifest.json` (core `balance.DatasetBalance.as_dict`). */
export interface LcaBalance {
  dataset: string;
  basis: string;
  /** Relative, e.g. 0.05. */
  tolerance: number;
  tolerance_basis: string;
  /** Per gate requirement (`lci-mass-balance`, `lci-element-balance`, `lci-carbon-origin`): `closed`, `open` or `not-assessable`. */
  status: Record<string, string>;
  /** What keeps a balance open or not assessable, each naming its residual. */
  problems: string[];
  mass: (LcaClosure & { unit: string }) | null;
  mass_unassessable: string | null;
  /** Per element symbol. */
  elements: Record<string, LcaClosure>;
  /** Material exchanges without a usable composition, and why. */
  no_composition: Record<string, string>;
  carbon:
    | (LcaClosure & {
        unit: string;
        inputs: Record<string, number>;
        outputs: Record<string, number>;
        declared_outputs: Record<string, number>;
        mismatched: string[];
        problems: string[];
      })
    | null;
  energy: {
    unit: string;
    inputs: Record<string, number>;
    outputs: Record<string, number>;
    /** Energy out over energy in; null when none enters. */
    closure: number | null;
    unclassified: string[];
    basis: string;
  };
  /** Exchange key -> why it is outside the mass and element balances. */
  excluded: Record<string, string>;
  /** Cut-off flows (`cutoff:` of the dataset), listed beside the balance, not counted in it; amount null: not known. */
  cutoff: Record<string, { direction: "input" | "output"; amount: number | null; unit: string }>;
}

/** One allocation method: the functional unit's share and the totals, or why it does not apply. */
export interface LcaAllocationMethod {
  method: string;
  /** The method the study uses. */
  current: boolean;
  share: number | null;
  totals: Record<string, number> | null;
  problem: string;
}

/** The distribution of one category's total per functional unit. */
export interface LcaStatistics {
  category: string;
  deterministic: number;
  mean: number;
  median: number;
  sd: number;
  /** 2.5th and 97.5th percentiles: the 95 % interval. */
  low: number;
  high: number;
  /** Inputs (`amount:<key>`, `factor:<id>`) by Spearman rank correlation with the total. */
  sensitivity: [string, number][];
}

export interface LcaUncertainty {
  iterations: number;
  seed: number;
  statistics: LcaStatistics[];
  varied: string[];
}

// -- techno-economic analysis (GET /api/tea) ------------------------------------------------------
// Every field is typed defensively: core grows the payload (new optional keys), a number that does
// not exist (no IRR, an infinite break-even) is null, and a TEA without a baseline has `{}` results.

/** The decision metrics core knows (newer cores may add more). */
export type TeaMetric = "npv" | "irr" | "lcop" | "cash_cost";

/** The decision the TEA informs (`decision:` of estimate/tea.yaml). */
export interface TeaDecision {
  question?: string;
  metric?: TeaMetric | (string & {});
  threshold?: number | null;
  /** The probability of meeting the threshold the decision asks for (0..1). */
  confidence?: number | null;
  alternatives?: string[];
}

/** The premises' basis, every value as text (product, boundary, discount rate, ...). */
export type TeaBasis = Record<string, string | number | boolean | null | undefined>;

/** One line of the capital cost build-up (ISBL, OSBL, owner's cost, contingency). */
export interface TeaCapexLine {
  id: string;
  title?: string;
  /** How it is computed, e.g. `0.3 x ISBL` or `given`. */
  basis?: string;
  value?: number | null;
  status?: string;
  source?: string;
  year?: number | null;
  /** The currency `value` is in (the estimate's; empty: the TEA's). */
  currency?: string;
  /** Its contribution in the TEA's currency and cost year. */
  tea_value?: number | null;
}

/** The AACE accuracy range of the fixed capital: the low and high ends, each a band `[from, to]`. */
export interface TeaCapexRange {
  class?: number | null;
  low?: number[] | null;
  high?: number[] | null;
}

/** A feed or product of the flowsheet with its price and value per year. */
export interface TeaFlowLine {
  /** `feed:<id>` or `product:<id>`. */
  key: string;
  title?: string;
  /** `material` or `energy`. */
  kind?: string;
  rate?: number | null;
  rate_unit?: string;
  /** `given`, `calculated` or `assumed`. */
  provenance?: string;
  price?: number | null;
  /** The price is per one of this (`t`, `MWh`, ...), in the report's currency. */
  price_unit?: string;
  /** Net income of the flow's lines per year at full load: revenue positive, cost negative
   * (null: unpriced). */
  per_year?: number | null;
  status?: string;
  source?: string;
  year?: number | null;
  /** Why the flow costs nothing (listed under `free:`), else empty. */
  free?: string;
  /** The component priced (e.g. `H2` of an off-gas); empty: the whole flow. */
  component?: string;
  /** The rate per flowsheet case, when the TEA weighs several cases. */
  per_case?: Record<string, number | null>;
  /** Every price of the flow (several when components are priced). */
  prices?: { component?: string; price?: number | null; unit?: string }[];
}

/** How the plant runs (`operation:` of estimate/tea.yaml, as evaluated). */
export interface TeaOperation {
  hours_per_year?: number | null;
  life_years?: number | null;
  /** Capacity fractions of the first operating years. */
  ramp_up?: number[];
  utilisation?: number | null;
  batches_per_year?: number | null;
  cycle_time?: number | null;
  /** The hours a year the cash flow counts. */
  operating_hours?: number | null;
  /** Flowsheet cases and their share of the year. */
  cases?: { case: string; share?: number | null }[];
}

/** Every priced line of the variable cost and revenue (`feed:X`, `product:Y@CO2`, `feed:POWER~summer`, `variable:<id>`, `emission:<id>`, `allowance:carbon`). */
export interface TeaLine {
  key: string;
  /** `main`, `feed`, `utility`, `chemical`, `catalyst`, `disposal`, `emission`, `incentive`, `byproduct`, `other`. */
  category?: string;
  /** A revenue (a product) rather than a cost. */
  revenue?: boolean;
  /** Per operating hour, in `unit`. */
  rate?: number | null;
  unit?: string;
  /** Currency per `unit`. */
  price?: number | null;
  per_year?: number | null;
  /** Price multipliers by operating year. */
  profile?: number[];
}

/** A variable cost the flowsheet does not carry (a chemical, a catalyst consumed, a fee). */
export interface TeaVariableItem {
  id: string;
  title?: string;
  /** `feed:<id>`, `product:<id>`, `hour` or `batch`. */
  per?: string;
  component?: string;
  /** Quantity of `unit` per kg/kWh of `per` (or per hour, per batch). */
  amount?: number | null;
  unit?: string;
  price?: number | null;
  category?: string;
  /** Quantity of `unit` per operating hour. */
  rate?: number | null;
  status?: string;
  source?: string;
  year?: number | null;
}

/** The priced emissions. */
export interface TeaEmissions {
  t_per_year?: number | null;
  free_t_per_year?: number | null;
  cost_per_year?: number | null;
  /** Per unit of the main product (the LCOP's unit). */
  per_unit?: number | null;
}

/** A recurring or one-off cost (catalyst replacement, turnaround, a grant). */
export interface TeaEvent {
  id: string;
  title?: string;
  /** `replacement`, `turnaround`, `sustaining`, `one_off`. */
  kind?: string;
  amount?: number | null;
  every_years?: number | null;
  every_hours?: number | null;
  first_year?: number | null;
  downtime_days?: number | null;
  /** `expense` or `capital`. */
  treatment?: string;
  status?: string;
  source?: string;
}

/** One category of the cost of production per unit of the main product (they sum to the LCOP). */
export interface TeaCostOfProduction {
  /** A line category, or `fixed`, `events`, `capital_and_tax`; a credit (by-product) is negative. */
  category: string;
  per_unit?: number | null;
  per_year?: number | null;
}

/** A fixed operating cost (maintenance, labour, insurance, ...). */
export interface TeaOpexLine {
  id: string;
  title?: string;
  basis?: string;
  per_year?: number | null;
  status?: string;
  source?: string;
  year?: number | null;
}

/** The baseline's results; `{}` when the TEA has no baseline. */
export interface TeaResults {
  isbl?: number | null;
  osbl?: number | null;
  owners_cost?: number | null;
  contingency?: number | null;
  fixed_capital?: number | null;
  working_capital?: number | null;
  revenue_per_year?: number | null;
  variable_cost_per_year?: number | null;
  fixed_cost_per_year?: number | null;
  npv?: number | null;
  /** A fraction (0.12 is 12 %); null when there is none. */
  irr?: number | null;
  /** Levelised cost of the main product, in `lcop_unit`. */
  lcop?: number | null;
  lcop_unit?: string;
  /** The cash cost of the main product (no capital charge), in `lcop_unit`. */
  cash_cost?: number | null;
  /** The LCOP without incentives (null: there are none). */
  lcop_unsubsidised?: number | null;
  /** The main product per year, in `main_unit` (e.g. `kg/a`). */
  main_per_year?: number | null;
  main_unit?: string;
  operating_hours?: number | null;
  /** The main product has a price: false means NPV and IRR leave out its revenue. */
  main_priced?: boolean | null;
  payback_years?: number | null;
  /** The decision metric meets the threshold (null: no threshold or no value). */
  meets?: boolean | null;
}

/** One year of the cash flow (in the report's currency); newer cores may add columns. */
export interface TeaCashflowRow {
  year: number;
  /** `construction` or `operation` (newer cores may add more). */
  phase?: "construction" | "operation" | (string & {});
  capacity?: number | null;
  capital?: number | null;
  working_capital?: number | null;
  revenue?: number | null;
  /** Events expensed that year. */
  periodic?: number | null;
  variable_cost?: number | null;
  fixed_cost?: number | null;
  depreciation?: number | null;
  tax?: number | null;
  cash_flow?: number | null;
  discounted?: number | null;
  cumulative?: number | null;
  [column: string]: number | string | boolean | null | undefined;
}

/** A scenario of estimate/tea.yaml evaluated: its fixed capital and metrics. */
export interface TeaScenario {
  id: string;
  title?: string;
  source?: string;
  fixed_capital?: number | null;
  npv?: number | null;
  irr?: number | null;
  lcop?: number | null;
  cash_cost?: number | null;
  meets?: boolean | null;
}

/** An input the sensitivity and break-even vary (`price:feed:POWER`, `capex:isbl`, ...). */
export interface TeaInput {
  id: string;
  value?: number | null;
  unit?: string;
  status?: string;
  source?: string;
}

/** The value of an input at which the decision metric reaches the threshold (null: none in range). */
export interface TeaTurn {
  input: string;
  base?: number | null;
  unit?: string;
  multiplier?: number | null;
  value?: number | null;
}

/** One tornado bar: the decision metric at the low and high multiplier of an input. */
export interface TeaTornadoBar {
  input: string;
  /** Multipliers of the input. */
  low?: number | null;
  high?: number | null;
  /** `P10/P90`, `swing`, `default`, ... */
  basis?: string;
  /** The decision metric (absolute) at the low and high end; null when it does not exist. */
  at_low?: number | null;
  at_high?: number | null;
  width?: number | null;
}

/** The Monte Carlo distribution of one metric. */
export interface TeaStatistic {
  metric: string;
  unit?: string;
  deterministic?: number | null;
  mean?: number | null;
  p10?: number | null;
  p50?: number | null;
  p90?: number | null;
  /** Iterations where the metric exists (an IRR may not). */
  valid?: number | null;
  /** Inputs by Spearman rank correlation with the metric. */
  sensitivity?: [string, number][];
}

export interface TeaUncertainty {
  iterations?: number | null;
  seed?: number | null;
  statistics?: TeaStatistic[];
  varied?: string[];
  /** P(the decision metric meets the threshold). */
  probability?: number | null;
}

/**
 * What core's boundary check found (`boundary` of `GET /api/tea`): `complete` when its rules
 * (`checked`; `noted` are info only) warn of no gap, which is not a complete inventory
 * (`not_checked`); the gaps (the `cheme.boundary-*` findings, also in `findings`); the terminals
 * by category; the steps with a duty but no energy stream; and the products without a category
 * that the operating cost counts at no cost.
 */
export interface TeaBoundary {
  complete: boolean;
  categories: Record<string, string[]>;
  unassigned_duties: string[];
  checked: string[];
  noted: string[];
  not_checked: string[];
  gaps: Finding[];
  excluded_products: string[];
}

/** A plant of a library server (`GET /api/plants`, core's ADR 0034). */
export interface PlantEntry {
  id: string;
  /** Its folder, relative to the library. */
  path: string;
  /** From `plant.yaml`; null when it does not validate (`error` says why). */
  name: string | null;
  stage: string | null;
  sheets: number;
  /** The level `checks/maturity.json` records (never evaluated live), and when. */
  maturity: string | null;
  maturity_checked: string | null;
  /** From a `process.yaml` beside `plant.yaml` (process-library), when there is one. */
  title: string | null;
  summary: string | null;
  families: string[];
  error: string | null;
}

/** `GET /api/plants` of a library server: a 404 means a server of one plant. */
export interface PlantsIndex {
  root_name: string;
  plants: PlantEntry[];
}

/** `GET /api/tea`: `cheme assess tea --json` of a revision, without the source. */
export interface TeaReport {
  rev?: string | null;
  currency?: string;
  cost_year?: number | null;
  /** The premises are an example: the results evaluate nothing real. */
  example?: boolean;
  stage?: string | null;
  /** The AACE class the capital cost claims, and the one the stage expects. */
  estimate_class?: number | null;
  expected_class?: number | null;
  decision?: TeaDecision | null;
  metric?: TeaMetric | (string & {});
  threshold?: number | null;
  basis?: TeaBasis | null;
  /** Core's boundary check; older cores leave it out. */
  boundary?: TeaBoundary | null;
  operation?: TeaOperation | null;
  capex?: TeaCapexLine[];
  capex_range?: TeaCapexRange | null;
  flows?: TeaFlowLine[];
  lines?: TeaLine[];
  variable?: TeaVariableItem[];
  emissions?: TeaEmissions | null;
  opex?: TeaOpexLine[];
  events?: TeaEvent[];
  results?: TeaResults | null;
  cost_of_production?: TeaCostOfProduction[];
  cashflow?: TeaCashflowRow[];
  scenarios?: TeaScenario[];
  inputs?: TeaInput[];
  break_even?: TeaTurn[];
  tornado?: TeaTornadoBar[];
  uncertainty?: TeaUncertainty | null;
  findings?: Finding[];
}

/** What an interlock does to one item (core's `Action`). */
export type InterlockAction = "trip" | "stop" | "start" | "close" | "open" | "depressurize" | "alarm";

/** One interlock of `control/cause-effect.yaml`, as listed there. */
export interface Interlock {
  id: string;
  title: string;
  /** The instrument (or other tag) and its condition, e.g. LIA-4107 at LALL. */
  cause: { tag: string; condition: string };
  effects: { tag: string; action: InterlockAction }[];
  /** The sheet id the interlock is drawn on (`P-04`), if given. */
  sheet: string | null;
  /** SIL from the screening, if done. */
  sil: string | number | null;
  /** The trip condition when it is more than the cause: all/any/vote of conditions. */
  logic?: ControlCondition | null;
  delay?: { value: number; unit: string } | null;
  /** True: the trip stays until reset; null: not stated. */
  latching?: boolean | null;
  reset?: "manual" | "automatic" | null;
  bypass?: string | null;
  notes: string;
}

/** A condition of core's control formats (`domains/control/schemas.py` `Condition`), as dumped by alias. */
export interface ControlCondition {
  tag?: string | null;
  loop?: string | null;
  interlock?: string | null;
  sequence?: string | null;
  step?: string | null;
  state?: string;
  all?: ControlCondition[] | null;
  any?: ControlCondition[] | null;
  vote?: { k: number; of: ControlCondition[] } | null;
  text?: string | null;
  unresolved?: string | null;
  delay?: { value: number; unit: string } | null;
  deadband?: { value: number; unit: string } | null;
}

/** Review status of a control file, from the review records (core `foundation.reviews.coverage`). */
export type ControlStatus = "drafted" | "reviewed" | "accepted";

/** One control file of `GET /api/control` with its review status. */
export interface ControlFile {
  path: string;
  kind: "loops" | "sequences" | "interlocks" | "narrative" | "philosophy";
  status: ControlStatus;
  detail: string;
  /** The review record that decides the status; null when none covers the file. */
  record: string | null;
  reviewed_commit?: string;
  reviewer?: string;
  reviewer_kind?: "human" | "agent" | "self";
}

/** Findings about a loop or sequence, by level. */
export interface ControlCounts {
  error: number;
  warning: number;
  info: number;
}

/** One loop of `control/loops.yaml` as the loop summary shows it (core `report.loop_row`). */
export interface ControlLoop {
  id: string;
  title: string;
  section: string | null;
  variable: string | null;
  measurement: string[];
  controller: string | null;
  action: "direct" | "reverse" | null;
  /** `FV-101 fail closed`, `... at 0-50 %`; `fail ?` when not stated. */
  final_elements: string[];
  /** `setpoint 3600 kg/h (given: basis of design) [design]`, or `setpoint ? (why)`. */
  targets: string[];
  modes: string[];
  normal_mode: string | null;
  links: string[];
  alarms: string[];
  interlocks: string[];
  unresolved: string[];
  findings: ControlCounts;
  /** The entry as written (by alias, defaults left out). */
  record: Record<string, unknown>;
}

export interface ControlStep {
  id: string;
  title: string;
  entry: string;
  actions: string[];
  complete: string;
  timeout: string;
  next: string;
  operator: string;
}

/** One sequence of `control/sequences.yaml` as the sequence report shows it (core `report.sequence_row`). */
export interface ControlSequence {
  id: string;
  title: string;
  mode: "startup" | "shutdown" | "abnormal" | "normal" | "other";
  section: string | null;
  permissives: string[];
  interlocks: string[];
  steps: ControlStep[];
  abort: { condition: string; actions: string[]; then: string | null; notes: string } | null;
  reset: { latching: boolean | null; manual: boolean | null; condition: string; restart: string } | null;
  unresolved: string[];
  findings: ControlCounts;
  record: Record<string, unknown>;
}

/** A process section of the narrative's front matter (defaults left out). */
export interface ControlSection {
  id: string;
  title?: string;
  equipment?: string[];
  blocks?: string[];
  cases?: string[];
  modes?: string[];
  loops?: string[];
  sequences?: string[];
  interlocks?: string[];
}

/** `process/narrative.md` or `control/philosophy.md`: what its front matter names. */
export interface ControlDocument {
  path: string;
  kind: "narrative" | "philosophy";
  /** False when its front matter does not load (the findings say why). */
  valid: boolean;
  sections?: ControlSection[];
  objectives?: { id: string; title: string; loops?: string[] }[];
  failures?: { id: string; title: string; response?: string; loops?: string[]; sequences?: string[]; interlocks?: string[] }[];
  unresolved?: string[];
  headings: string[];
}

/** `GET /api/control` (`cheme control report --json`): the working tree's control records. */
export interface ControlReport {
  present: boolean;
  files: ControlFile[];
  loops: ControlLoop[];
  sequences: ControlSequence[];
  documents: ControlDocument[];
  findings: Finding[];
  source: { commit: string | null; dirty: string[]; fingerprints: Record<string, string> };
}

/** One cause of the matrix: an interlock, with its action in each effect column ("" when none). */
export interface InterlockRow {
  id: string;
  title: string;
  cause: string;
  condition: string;
  sheet: string | null;
  sil: string | number | null;
  /**
   * Aligned with {@link InterlockMatrix.columns}: the cell's action, "" for none, or several
   * actions joined by " + " in the order given (`close + alarm`) when one interlock has more than
   * one effect on the tag. See `cellActions` in `lib/causeEffect.ts`.
   */
  cells: string[];
}

/** `GET /api/interlocks`: `control/cause-effect.yaml` at a revision and its cause & effect matrix. */
export interface InterlockMatrix {
  /** The commit shown; null for the working tree. */
  rev: string | null;
  file: string;
  interlocks: Interlock[];
  /** The effect tags, in the order they first appear. */
  columns: string[];
  rows: InterlockRow[];
}

/** An issue's engineering type, from its `type:` label (core `project/issues.py` `TYPES`). */
export type IssueType = "action" | "hold" | "tq" | "change";

/** Where an issue stands: from its `status:` label while open (`open` without one); `closed` once closed, i.e. verified. */
export type IssueStatus = "open" | "in-progress" | "for-verification" | "closed";

/** One GitHub issue of the plant as an engineering item (core `project/issues.py` `Issue`). */
export interface Issue {
  number: number;
  title: string;
  state: "open" | "closed";
  status: IssueStatus;
  /** `type:` label; null when it has none (an untyped issue). */
  type: IssueType | null;
  /**
   * The stage gate it must be closed before: the earliest of its `gate:` labels (a stage id, or
   * as labelled when it names no stage of the plant); null when none.
   */
  gate: string | null;
  /** Every `gate:` label of the issue, earliest first (`gate` is the first); empty when none. */
  gates: string[];
  /** `discipline:` labels, sorted. */
  disciplines: string[];
  /** `source:` label: design-review, hazop, vendor, client, ... */
  source: string | null;
  /** `waiting:` label: `input` (vendor, client, HAZOP / LOPA) or `work` (another issue). */
  waiting: "input" | "work" | null;
  /** The issue on GitHub. */
  url: string;
  created: string;
  updated: string;
  closed: string | null;
}

/**
 * `GET /api/issues` (`cheme issues --json`): the plant's GitHub issues, read live (cached five
 * minutes by the server), with the counts the `kind: issues` gates use and new-issue links. A 404
 * means plant.yaml declares no `issues:`, a 503 that GitHub cannot be read (no token, offline).
 */
export interface IssuesReport {
  /** `owner/name` of the GitHub repository. */
  repository: string;
  /** The plant's label there (`process:asu-1`). */
  label: string;
  /** The repository's issue list filtered by the plant's label. */
  web: string;
  /**
   * A link per type that opens the issue form with the label and the form's `process` field
   * filled in (keys among action, hold, tq, change); `{choose}` (the template chooser) when
   * plant.yaml names no forms. A viewer may append `&refs=<text>` for the form's References field.
   */
  new: Partial<Record<IssueType | "choose", string>>;
  /** The plant's current stage id (plant.yaml `stage`). */
  stage: string | null;
  /** The stage ids in order. */
  stages: string[];
  /** Open issues per gate (`none` without one) and type (`other` without one). */
  open_by_gate: Record<string, Record<string, number>>;
  /**
   * Per stage, the numbers of the open issues blocking its gate: a `gate:` at or before it, or
   * one that names no stage of the plant (a mistyped `gate:Basic` blocks every gate).
   */
  blocking: Record<string, number[]>;
  /** Every issue, open and closed, newest first. */
  issues: Issue[];
}

/**
 * The JSON answer of each endpoint (`/api/<key>`): the one place that ties an endpoint to its
 * response type, so every request below and the endpoint names in its URL agree.
 */
export interface JsonEndpoints {
  repo: RepoInfo;
  branches: Branch[];
  log: Commit[];
  tree: TreeEntry[];
  diff: SheetDiff;
  validate: ValidationReport;
  checks: ChecksReport;
  /** `POST`, with the token of `session`. */
  "checks/run": ChecksReport;
  session: Session;
  yaml: YamlDoc;
  streams: StreamTable;
  layout: Layout;
  mto: MtoReport;
  "estimate/equipment": EquipmentEstimate;
  lca: LcaReport;
  tea: TeaReport;
  interlocks: InterlockMatrix;
  control: ControlReport;
  issues: IssuesReport;
  impact: ImpactReport;
  status: PlantStatus;
  simulation: SimulationView;
  datasheets: DatasheetIndex;
  [tag: `datasheets/${string}`]: DatasheetDetail;
  reactions: ReactionsView;
  kinetics: KineticsView;
  library: LibraryView;
  /** Checked at run time against `cheme/maturity-report/v1` (src/lib/maturity.ts). */
  maturity: unknown;
}

export type JsonEndpoint = keyof JsonEndpoints;

/** A revision to read; absent, null or empty means the working tree. */
export type Rev = string | null | undefined;

export type Query = Record<string, QueryValue>;

/** Base URL of the server; empty means same origin (the Vite proxy or `cheme serve --ui`). */
export const API_BASE: string = import.meta.env?.VITE_CHEME_API ?? "";

// The plant's prefix on a library server (`/p/<id>`, core's ADR 0034), set once at startup.
let plantPrefix = "";

/** Talk to the plant under `/p/<id>/` of a library server (main.ts, from the page's path). */
export function usePlant(id: string | null): void {
  plantPrefix = id ? `/p/${encodeURIComponent(id)}` : "";
}

/**
 * `/api/<endpoint>?a=b` of the plant shown, leaving out parameters that are undefined, null or
 * empty strings (so an absent `rev` means the working tree). Keys are sorted for stable URLs.
 */
export function apiUrl(endpoint: string, query: Query = {}, base: string = API_BASE.replace(/\/+$/, "") + plantPrefix): string {
  const name = endpoint.replace(/^\/+/, "").replace(/^api\//, "");
  const params = new URLSearchParams();
  for (const key of Object.keys(query).sort()) {
    const value = query[key];
    if (value === undefined || value === null || value === "") continue;
    params.append(key, String(value));
  }
  const search = params.toString();
  return `${base.replace(/\/+$/, "")}/api/${name}${search ? `?${search}` : ""}`;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly url: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function errorFrom(response: Response, url: string): Promise<ApiError> {
  let message = `${response.status} ${response.statusText}`.trim();
  try {
    const text = await response.text();
    try {
      const body = JSON.parse(text) as { error?: unknown; detail?: unknown };
      const detail = body.error ?? body.detail;
      if (typeof detail === "string" && detail) message = detail;
      else if (detail !== undefined) message = JSON.stringify(detail);
    } catch {
      if (text && text.length < 500) message = text;
    }
  } catch {
    /* keep the status line */
  }
  return new ApiError(response.status, message, url);
}

type Fetch = typeof fetch;
let fetchImpl: Fetch = (...args) => fetch(...args);

/** Replace the fetch implementation (tests). */
export function setFetch(impl: Fetch): void {
  fetchImpl = impl;
}

async function request(
  url: string,
  signal?: AbortSignal,
  init: { method?: string; headers?: Record<string, string> } = {},
): Promise<Response> {
  let response: Response;
  try {
    response = await fetchImpl(url, {
      ...(signal ? { signal } : {}),
      method: init.method ?? "GET",
      headers: { Accept: "application/json, text/plain, */*", ...init.headers },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "Cannot reach the cheme-as-code server. Is `cheme serve` running?", url);
  }
  if (!response.ok) throw await errorFrom(response, url);
  return response;
}

// Where GETs go: the server (default) or a static snapshot (src/dataSource.ts, `?data=`).
let snapshot: SnapshotSource | null = null;

/** Answer requests from a static snapshot instead of the server (null: back to the server). */
export function useSnapshot(source: SnapshotSource | null): void {
  snapshot = source;
}

/** The open snapshot, or null when the viewer talks to a server. */
export function currentSnapshot(): SnapshotSource | null {
  return snapshot;
}

async function get(endpoint: string, query: Query = {}, signal?: AbortSignal): Promise<Response> {
  if (!snapshot) return request(apiUrl(endpoint, query), signal);
  const url = apiUrl(endpoint, query, snapshot.base);
  const response = await snapshot.fetch(endpoint, query, signal);
  if (!response.ok) throw await errorFrom(response, url);
  return response;
}

/**
 * The body of an answer to `endpoint`, as {@link JsonEndpoints} types it. The client trusts the
 * server's contract (tests/apiContract.test.ts checks it against real answers) and does not
 * validate at run time, so this is the one unchecked step from JSON to the response types.
 */
async function readJson<E extends JsonEndpoint>(response: Response, _endpoint: E): Promise<JsonEndpoints[E]> {
  return (await response.json()) as JsonEndpoints[E];
}

async function getJson<E extends JsonEndpoint>(endpoint: E, query?: Query, signal?: AbortSignal): Promise<JsonEndpoints[E]> {
  const response = await get(endpoint, query, signal);
  return readJson(response, endpoint);
}

/**
 * The plants of a library server, from its root (never a plant's prefix, never a snapshot); a
 * 404 (an ApiError) means the server serves one plant.
 */
export async function getPlants(signal?: AbortSignal): Promise<PlantsIndex> {
  const response = await request(apiUrl("plants", {}, API_BASE), signal);
  return (await response.json()) as PlantsIndex;
}

async function getText(endpoint: string, query?: Query, signal?: AbortSignal): Promise<string> {
  const response = await get(endpoint, query, signal);
  return response.text();
}

function snapshotRefusal(what: string): ApiError {
  return new ApiError(405, `${what} needs a running server (cheme serve); this is a static snapshot.`, "");
}

let session: Promise<Session> | null = null;

/**
 * Run the checks of `checks/checks.yaml` on the working tree (`POST /api/checks/run`). It runs
 * shell commands, so the server wants the per-launch token of `GET /api/session` in a header.
 * The token is fetched once; a 403 (server restarted) fetches it again and retries once.
 */
async function runChecks(signal?: AbortSignal): Promise<ChecksReport> {
  if (snapshot) throw snapshotRefusal("Running the checks");
  const endpoint = "checks/run";
  const url = apiUrl(endpoint);
  for (let attempt = 0; ; attempt++) {
    session ??= getJson("session", {}, signal);
    let current: Session;
    try {
      current = await session;
    } catch (error) {
      session = null;
      throw error;
    }
    try {
      const response = await request(url, signal, { method: "POST", headers: { [current.header]: current.token } });
      return await readJson(response, endpoint);
    } catch (error) {
      if (error instanceof ApiError && error.status === 403 && attempt === 0) {
        session = null;
        continue;
      }
      throw error;
    }
  }
}

/** Forget the cached session token (tests). */
export function resetSession(): void {
  session = null;
}

/** Revision query value: `undefined` (working tree) for empty input. */
export function revParam(rev: Rev): string | undefined {
  return rev ? rev : undefined;
}

/** The interlocks at `rev`; a 404 means no `control/cause-effect.yaml` there (or an older server), a 422 that it does not load. */
export function fetchInterlocks(rev?: Rev, signal?: AbortSignal): Promise<InterlockMatrix> {
  return getJson("interlocks", { rev: revParam(rev) }, signal);
}

export const api = {
  repo: (signal?: AbortSignal) => getJson("repo", {}, signal),
  branches: (signal?: AbortSignal) => getJson("branches", {}, signal),
  log: (opts: { limit?: number | undefined; path?: string | undefined; rev?: Rev } = {}, signal?: AbortSignal) =>
    getJson("log", { limit: opts.limit ?? 50, path: opts.path, rev: revParam(opts.rev) }, signal),
  tree: (rev?: Rev, signal?: AbortSignal) =>
    getJson("tree", { rev: revParam(rev) }, signal),
  file: (path: string, rev?: Rev, signal?: AbortSignal) =>
    getText("file", { path, rev: revParam(rev) }, signal),
  pidSvgUrl: (path: string, rev?: Rev) =>
    snapshot?.url("pid.svg", { path, rev: revParam(rev) }) ?? apiUrl("pid.svg", { path, rev: revParam(rev) }),
  pidSvg: (path: string, rev?: Rev, signal?: AbortSignal) =>
    getText("pid.svg", { path, rev: revParam(rev) }, signal),
  diff: (path: string, oldRev: string, newRev?: Rev, signal?: AbortSignal) =>
    snapshot
      ? Promise.reject(snapshotRefusal("Comparing revisions"))
      : getJson("diff", { path, old: oldRev, new: revParam(newRev) }, signal),
  validate: (signal?: AbortSignal) => getJson("validate", {}, signal),
  checks: (opts: { rev?: Rev } = {}, signal?: AbortSignal) =>
    getJson("checks", { rev: revParam(opts.rev) }, signal),
  runChecks,
  yaml: (path: string, rev?: Rev, signal?: AbortSignal) =>
    getJson("yaml", { path, rev: revParam(rev) }, signal),
  /** Stream table of `process/flowsheet.yaml` for one case (default case when empty); 404 without one. */
  streams: (opts: { case?: string | null | undefined; rev?: Rev } = {}, signal?: AbortSignal) =>
    getJson("streams", { case: opts.case || undefined, rev: revParam(opts.rev) }, signal),
  /** 3D layout (site plan, buildings, equipment placement); a 404 means no layout files at `rev`. */
  layout: (rev?: Rev, signal?: AbortSignal) => getJson("layout", { rev: revParam(rev) }, signal),
  /**
   * 2D plan of the layout (`cheme layout render --plan`), an SVG; a 404 means an older server
   * or no model. `level` (a building or structure level id) or `z` (`"a,b"`, a cut range in m).
   */
  layoutPlanSvg: (opts: { rev?: Rev; level?: string | null | undefined; z?: string | null | undefined } = {}, signal?: AbortSignal) =>
    getText("layout/plan.svg", { rev: revParam(opts.rev), level: opts.level || undefined, z: opts.z || undefined }, signal),
  /** Material take-off (and estimate) of the committed 3D model; a 404 means no model at `rev` (or an older server). */
  mto: (rev?: Rev, signal?: AbortSignal) => getJson("mto", { rev: revParam(rev) }, signal),
  /** The equipment estimate at `rev`; a 404 means nothing to estimate there (no equipment list) or an older server. */
  equipmentEstimate: (rev?: Rev, signal?: AbortSignal) =>
    getJson("estimate/equipment", { rev: revParam(rev) }, signal),
  /** The LCA at `rev`; a 404 means no `lca/lca.yaml` there (or an older server), a 422 that it does not compute. */
  lca: (rev?: Rev, signal?: AbortSignal) => getJson("lca", { rev: revParam(rev) }, signal),
  /** The TEA at `rev`: a 404 means no `estimate/tea.yaml` there (or an older server), a 422 that it does not compute. */
  tea: (rev?: Rev, signal?: AbortSignal) => getJson("tea", { rev: revParam(rev) }, signal),
  interlocks: fetchInterlocks,
  /**
   * Loops, sequences, narrative and control philosophy of the working tree with their review
   * status and findings; a 404 means the plant has none (or an older server, or a snapshot without it).
   */
  control: (signal?: AbortSignal) => getJson("control", {}, signal),
  /**
   * The plant's issues as GitHub has them now (never at a revision); a 404 means plant.yaml
   * declares none (or an older server, or a snapshot without them), a 503 that they cannot be read.
   */
  issues: (signal?: AbortSignal) => getJson("issues", {}, signal),
  /** 2D section of the layout at `x=` or `y=` (m), an SVG; a 404 means an older server or no model. */
  layoutSectionSvg: (opts: { rev?: Rev; x?: number | null | undefined; y?: number | null | undefined }, signal?: AbortSignal) =>
    getText("layout/section.svg", { rev: revParam(opts.rev), x: opts.x ?? undefined, y: opts.y ?? undefined }, signal),
  /** Review-needed artifacts of the working tree; a 404 means an older server without it. */
  impact: (signal?: AbortSignal) => getJson("impact", {}, signal),
  /**
   * `cheme status --json` of the working tree (review findings, sign-offs, validation counts).
   * Slow on a large plant (it validates everything). A 404 means a snapshot or an older server.
   */
  status: (signal?: AbortSignal) => getJson("status", {}, signal),
  /**
   * `cheme maturity --json` of the working tree, evaluated on every request (some 30 s on a
   * large plant: the engineering level validates the whole repository). It has no `rev`; a 404
   * means an older server or a snapshot without it, a 422 that the plant does not load.
   * Typed `unknown`: the caller checks the schema (src/lib/maturity.ts).
   */
  maturity: (signal?: AbortSignal) => getJson("maturity", {}, signal),
  /** A repository file's bytes as `/api/file` serves it (UTF-8, no BOM stripped), e.g. to compare a fingerprint. */
  fileBytes: async (path: string, rev?: Rev, signal?: AbortSignal): Promise<Uint8Array> =>
    new Uint8Array(await (await get("file", { path, rev: revParam(rev) }, signal)).arrayBuffer()),
  /**
   * `process/simulation.yaml` with the run `cheme process simulate --fill` recorded for the case
   * (default case when empty); a 404 means no simulation file there (or an older server or a
   * snapshot without it), a 422 that it does not load or the case is unknown.
   */
  simulation: (opts: { case?: string | null | undefined; rev?: Rev } = {}, signal?: AbortSignal) =>
    getJson("simulation", { case: opts.case || undefined, rev: revParam(opts.rev) }, signal),
  /** The datasheets at `rev`; a 404 means none there, an older server or a snapshot without them. */
  datasheets: (rev?: Rev, signal?: AbortSignal) => getJson("datasheets", { rev: revParam(rev) }, signal),
  /** One datasheet at `rev`; a 404 means no datasheet of `tag` there (or an older server, or a snapshot without it). */
  datasheet: (tag: string, rev?: Rev, signal?: AbortSignal) =>
    getJson(`datasheets/${encodeURIComponent(tag)}`, { rev: revParam(rev) }, signal),
  /**
   * The outline drawing of `tag`: the committed `equipment/datasheets/<TAG>.svg`, or (none
   * committed, or `generated`) the one `cheme datasheets drawing` would write. 404: unknown tag;
   * 422: the datasheet does not validate.
   */
  datasheetDrawing: async (tag: string, opts: { rev?: Rev; generated?: boolean | undefined } = {}, signal?: AbortSignal): Promise<DatasheetDrawing> => {
    const response = await get(`datasheets/${encodeURIComponent(tag)}.svg`, { rev: revParam(opts.rev), generated: opts.generated ? "true" : undefined }, signal);
    const kind = response.headers.get("x-cheme-drawing");
    const current = response.headers.get("x-cheme-drawing-current");
    return {
      svg: await response.text(),
      kind: kind === "committed" || kind === "generated" ? kind : null,
      current: current === "true" ? true : current === "false" ? false : null,
    };
  },
  /** URL of the outline drawing, for a download link (the snapshot's file in a snapshot; null when it holds none). */
  datasheetDrawingUrl: (tag: string, opts: { rev?: Rev; generated?: boolean | undefined } = {}): string | null => {
    const query = { rev: revParam(opts.rev), generated: opts.generated ? "true" : undefined };
    const endpoint = `datasheets/${encodeURIComponent(tag)}.svg`;
    return snapshot ? snapshot.url(endpoint, query) : apiUrl(endpoint, query);
  },
  /** URL of a repository file as `/api/file` serves it (the snapshot's file in a snapshot; null when it holds none). */
  fileUrl: (path: string, rev?: Rev): string | null =>
    snapshot ? snapshot.url("file", { path, rev: revParam(rev) }) : apiUrl("file", { path, rev: revParam(rev) }),
  /** The reactions and reactors for the case; a 404 means no `process/reactions.yaml` there (or an older server), a 422 that it does not load. */
  reactions: (opts: { case?: string | null | undefined; rev?: Rev } = {}, signal?: AbortSignal) =>
    getJson("reactions", { case: opts.case || undefined, rev: revParam(opts.rev) }, signal),
  /** The kinetic data and their fits at `rev`; a 404 means none there (or an older server, or a snapshot without them). */
  kinetics: (rev?: Rev, signal?: AbortSignal) => getJson("kinetics", { rev: revParam(rev) }, signal),
  /** The reaction library marked by what the plant has at `rev`; a 404 means an older server (or a snapshot without it). */
  library: (rev?: Rev, signal?: AbortSignal) => getJson("library", { rev: revParam(rev) }, signal),
};
