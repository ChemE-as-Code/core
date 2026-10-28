<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { api, ApiError, type DrawingState } from "@/api";
import DatasheetBasis from "@/components/DatasheetBasis.vue";
import FindingsList from "@/components/FindingsList.vue";
import JsonTree from "@/components/JsonTree.vue";
import LoadState from "@/components/LoadState.vue";
import SvgPane, { type Layer } from "@/components/SvgPane.vue";
import { store, whenRepo } from "@/store";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { pathSegments, shortRev } from "@/lib/format";
import { createView } from "@/lib/panzoom";
import { sanitizeSvg, type SanitizedSvg } from "@/lib/sanitize";
import { DATASHEET_DIR } from "@/lib/studies";
import {
  countValues,
  LINE_LIST,
  loadDatasheetPage,
  materialClassText,
  serverHasDatasheets,
  valueText,
  VALUE_SECTIONS,
  type DatasheetMaterial,
  type DatasheetPage,
  type DatasheetRow,
  type DatasheetValue,
} from "@/lib/datasheets";

const route = useRoute();
const { rev, withRev } = useRev();
const tag = computed(() => String(route.params.tag ?? ""));

// `/api/datasheets/{tag}` when the server has it; else the tree and `/api/yaml` (no drawing state, no findings).
const page = useAsync<DatasheetPage>(async (signal) => loadDatasheetPage(tag.value, rev.value, serverHasDatasheets(await whenRepo()), signal), [tag, rev]);
const ds = computed(() => page.data.value?.sheet ?? null);
const detail = computed(() => page.data.value?.detail ?? null);
const path = computed(() => page.data.value?.path ?? null);
const missing = computed(() => Boolean(page.data.value) && !path.value);
const counts = computed(() => (ds.value ? countValues(ds.value) : null));
/** The server's counts (every field, core's `field_counts`); null on the tree path. */
const serverCounts = computed(() => detail.value?.summary.counts ?? null);
const sections = computed(() => {
  const sheet = ds.value;
  if (!sheet) return [];
  return VALUE_SECTIONS.map((s) => {
    const rows: DatasheetRow[] = sheet[s.key];
    return { ...s, rows };
  }).filter((s) => s.rows.length);
});
const otherTypeSpecific = computed(() => Object.entries(ds.value?.type_other ?? {}));
const findings = computed(() => page.data.value?.findings ?? []);

// The P&ID and line-list links need the tree; the server path does not fetch it otherwise.
const tree = useAsync(async (signal) => (page.data.value?.treeKinds ? null : api.tree(rev.value, signal)), [rev, () => Boolean(page.data.value?.treeKinds)]);
const treeKinds = computed(() => page.data.value?.treeKinds ?? new Map((tree.data.value ?? []).map((e) => [e.path, e.kind] as const)));

const hasLayout = computed(() => Boolean(store.repo?.has_layout));
const hasLineList = computed(() => treeKinds.value.has(LINE_LIST));
/** A nozzle's source when it is a drawn sheet (`pid/P-01.xml`): its P&ID, the item selected by tag. */
const sheetLink = (source: string) => {
  const file = source.trim().split(/\s/)[0] ?? "";
  return treeKinds.value.get(file) === "pid" ? { name: "pid", params: { path: pathSegments(file) }, query: withRev(ds.value ? { select: ds.value.tag } : {}) } : null;
};
const sheetTitle = (source: string) => {
  const file = source.trim().split(/\s/)[0] ?? "";
  return store.repo?.sheets.find((s) => s.file === file)?.id ?? file;
};

/** Why a value is marked: the assumption's reason, else its source. */
const markTitle = (v: DatasheetValue) => [v.assumed ? "assumed" : "", v.reason || v.source].filter(Boolean).join(": ");
const fmt = (n: number | null, digits = 3) => (n === null ? "" : n.toLocaleString("en", { maximumFractionDigits: digits }));
const isMaterial = (r: DatasheetRow): r is DatasheetMaterial => "material_class" in r;
const valueWithUnit = (v: DatasheetValue | null) => (v ? [valueText(v), v.open ? "" : v.unit].filter(Boolean).join(" ") : "");

// -- the outline drawing -----------------------------------------------------------------------

/** The drawing's state: the server's, or on the tree path `committed` (a file, not checked) / null (none). */
const drawingState = computed<DrawingState | "unchecked" | null>(() => {
  if (detail.value) return detail.value.drawing.state;
  return page.data.value?.treeDrawing ? "unchecked" : null;
});
/** Show the drawing generated from the datasheet now instead of the stale committed one. */
const preview = ref(false);
watch([tag, rev], () => (preview.value = false));

interface Drawing {
  svg: SanitizedSvg;
  /** What is shown: the committed file or the one generated from the datasheet. */
  kind: "committed" | "generated";
  /** The generated preview was asked for but is not there (a snapshot): the committed drawing is shown. */
  previewMissing: boolean;
}

const drawing = useAsync<Drawing | null>(
  async (signal) => {
    const p = page.data.value;
    if (!p) return null;
    if (p.detail) {
      const state = p.detail.drawing.state;
      if (state === "none") return null;
      const generated = preview.value && state === "stale";
      let answer;
      let previewMissing = false;
      try {
        answer = await api.datasheetDrawing(p.detail.tag, { rev: rev.value, generated }, signal);
      } catch (error) {
        // A snapshot holds the committed drawing only.
        if (!generated || !(error instanceof ApiError) || error.status !== 404) throw error;
        answer = await api.datasheetDrawing(p.detail.tag, { rev: rev.value }, signal);
        previewMissing = true;
      }
      // A snapshot sends no headers: the state says what the file is.
      const kind = answer.kind ?? (state === "missing" || (generated && !previewMissing) ? "generated" : "committed");
      return { svg: sanitizeSvg(answer.svg), kind, previewMissing };
    }
    if (p.treeDrawing) return { svg: sanitizeSvg(await api.file(p.treeDrawing, rev.value, signal)), kind: "committed", previewMissing: false };
    return null;
  },
  [page.data, preview],
);
const drawingError = computed(() => drawing.error.value);
const previewUnavailable = computed(() => Boolean(drawing.data.value?.previewMissing));
const layers = computed<Layer[]>(() => [{ id: "datasheet-drawing", svg: drawing.data.value?.svg ?? null }]);
const view = createView();
const downloadUrl = computed(() => {
  const p = page.data.value;
  if (!p) return null;
  if (p.detail) return api.datasheetDrawingUrl(p.detail.tag, { rev: rev.value, generated: drawing.data.value?.kind === "generated" && p.detail.drawing.state === "stale" });
  return p.treeDrawing ? api.fileUrl(p.treeDrawing, rev.value) : null;
});
const downloadName = computed(() => `${tag.value}${drawing.data.value?.kind === "generated" && drawingState.value !== "missing" ? "-generated" : ""}.svg`);
const drawingFile = computed(() => detail.value?.drawing.file ?? page.data.value?.treeDrawing ?? `${DATASHEET_DIR}/${tag.value}.svg`);
const writeHint = computed(() => `cheme datasheets drawing --tag ${tag.value} --write`);
const DRAWING_BADGE: Record<DrawingState | "unchecked", { cls: string; text: string; title: string }> = {
  current: { cls: "clean", text: "committed, current", title: "The committed drawing is what the datasheet gives now" },
  stale: { cls: "warning", text: "committed, stale", title: "The committed drawing is not what the datasheet gives now" },
  missing: { cls: "info", text: "generated preview", title: "No drawing committed: this is the one cheme datasheets drawing would write" },
  none: { cls: "error", text: "no drawing", title: "The datasheet does not validate" },
  unchecked: { cls: "", text: "committed", title: "This server cannot tell whether the drawing is what the datasheet gives now" },
};
</script>

<template>
  <div class="page datasheet">
    <p class="crumbs">
      <RouterLink :to="{ name: 'datasheets', query: withRev() }">Datasheets</RouterLink>
      <span class="faint"> / </span>{{ tag }}
    </p>
    <h1>
      {{ ds?.tag ?? tag }}
      <span v-if="ds?.type" class="badge info" data-type>{{ ds.type }}</span>
      <span v-if="ds?.draft" class="badge warning" data-draft title="A generated draft: the datasheets gate does not count it">draft</span>
      <span v-else-if="ds" class="badge clean">final</span>
      <small>{{ shortRev(rev) }}</small>
    </h1>
    <p v-if="ds?.service" class="service" data-service>{{ ds.service }}</p>

    <div class="toolbar">
      <span v-if="serverCounts" class="muted summary" data-counts>
        <strong :class="{ warn: serverCounts.assumed }">{{ serverCounts.assumed }} assumed</strong>,
        <strong :class="{ bad: serverCounts.tbd }">{{ serverCounts.tbd }} TBD</strong><template v-if="serverCounts.supplier">, {{ serverCounts.supplier }} awaiting supplier</template><template v-if="serverCounts.not_applicable">, {{ serverCounts.not_applicable }} not applicable</template>
      </span>
      <span v-else-if="counts" class="muted summary" data-counts>
        {{ counts.values }} values: <strong :class="{ warn: counts.assumed }">{{ counts.assumed }} assumed</strong>,
        <strong :class="{ bad: counts.tbd }">{{ counts.tbd }} TBD</strong><template v-if="counts.supplier">, {{ counts.supplier }} awaiting supplier</template><template v-if="counts.not_applicable">, {{ counts.not_applicable }} not applicable</template>
      </span>
      <span class="spacer" />
      <RouterLink v-if="hasLayout && ds" class="btn" :to="{ name: 'layout', query: withRev({ select: ds.tag }) }" title="Show the item in the 3D layout" data-action="show-3d">Show in 3D</RouterLink>
      <template v-if="path">
        <RouterLink class="btn" :to="{ name: 'yaml', params: { path: pathSegments(path) }, query: withRev() }" data-action="yaml">YAML</RouterLink>
        <RouterLink class="btn" :to="{ name: 'file', params: { path: pathSegments(path) }, query: withRev() }">Source</RouterLink>
      </template>
    </div>

    <LoadState :loading="page.loading.value && !page.data.value" :error="page.error.value" @retry="page.reload" />
    <p v-if="missing" class="notice" data-missing>No <code>{{ DATASHEET_DIR }}/{{ tag }}.yaml</code> at this revision.</p>
    <p v-if="detail && !detail.summary.valid" class="notice error" data-invalid>
      <code>{{ detail.file }}</code> does not validate (the findings say why): its values are shown as written, there is no drawing.
    </p>

    <FindingsList :findings="findings" label="Findings on the datasheet" title="Findings" data-section="findings" />

    <template v-if="ds">
      <section v-for="s in sections" :key="s.key" class="values" :data-section="s.key">
        <h2>{{ s.title }} <span class="muted">{{ s.rows.length }}</span></h2>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr>
                <th>parameter</th>
                <th class="num">value</th>
                <th>{{ s.key === "materials" ? "standard" : "unit" }}</th>
                <th>source</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in s.rows" :key="r.key" :data-key="r.key" :class="{ open: r.open === 'tbd', na: r.open === 'not_applicable' }">
                <td class="param">
                  <code>{{ r.key }}</code>
                </td>
                <td class="num value" :class="{ mat: isMaterial(r) }">
                  <span v-if="r.open === 'tbd'" class="badge error" data-open="tbd" :title="r.source || 'not known yet'">{{ valueText(r) }}</span>
                  <span v-else-if="r.open === 'supplier'" class="badge info" data-open="supplier" :title="r.reason || r.source">supplier</span>
                  <span v-else-if="r.open === 'not_applicable'" class="badge" data-open="not_applicable" :title="r.reason">n/a</span>
                  <template v-else>{{ valueText(r) }}</template>
                  <span v-if="r.assumed" class="prov assumed" data-assumed :title="markTitle(r)">A</span>
                  <template v-if="isMaterial(r)">
                    <span v-if="r.material_class" class="badge info chip" :data-material-class="r.material_class" title="Material class (matched by the take-off, the LCA and the cost factor)">{{ materialClassText(r.material_class) }}</span>
                  </template>
                </td>
                <td class="unit">
                  {{ r.unit }}<span v-if="isMaterial(r) && r.standard" class="standard" data-standard>{{ r.standard }}</span>
                </td>
                <td class="source">
                  <span v-if="r.source">{{ r.source }}</span>
                  <span v-if="r.reason" class="reason" data-reason><span class="faint">{{ r.open === "not_applicable" ? "not applicable" : "reason" }}:</span> {{ r.reason }}</span>
                  <DatasheetBasis :value="r" />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="ds.dimensions" class="dimensions" data-section="dimensions" aria-label="Main dimensions">
        <h2>
          Main dimensions
          <span v-if="ds.dimensions.orientation" class="badge" data-orientation>{{ ds.dimensions.orientation }}</span>
        </h2>
        <div class="dim-groups">
          <div v-for="g in ds.dimensions.groups" :key="g.key" class="dim-group" :data-group="g.key">
            <h3>{{ g.title }}</h3>
            <div class="table-wrap"><table class="data compact">
              <tbody>
                <tr v-for="r in g.rows" :key="r.key" :data-key="r.key" :class="{ open: r.open === 'tbd', na: r.open === 'not_applicable' }">
                  <th scope="row">{{ r.label }}</th>
                  <td class="num value">
                    <span v-if="r.open === 'tbd'" class="badge error" data-open="tbd" :title="r.source || 'not known yet'">{{ valueText(r) }}</span>
                    <span v-else-if="r.open === 'supplier'" class="badge info" data-open="supplier" :title="r.reason || r.source">supplier</span>
                    <span v-else-if="r.open === 'not_applicable'" class="badge" data-open="not_applicable" :title="r.reason">n/a</span>
                    <template v-else>{{ valueText(r) }}</template>
                    <span v-if="r.assumed" class="prov assumed" data-assumed :title="markTitle(r)">A</span>
                  </td>
                  <td class="unit">{{ r.open ? "" : r.unit }}</td>
                  <td class="source"><span :title="r.source">{{ r.reason || r.source }}</span><DatasheetBasis :value="r" /></td>
                </tr>
              </tbody>
            </table></div>
          </div>
        </div>
        <div v-if="ds.dimensions.sections.length" class="table-wrap col-sections" data-group="sections">
          <h3>Column sections</h3>
          <table class="data">
            <thead>
              <tr>
                <th>section</th>
                <th>internals</th>
                <th class="num" title="Above the bottom tangent line">bottom</th>
                <th class="num">height</th>
                <th class="num">count</th>
                <th class="num">spacing</th>
                <th>notes</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="sec in ds.dimensions.sections" :key="sec.id" :data-column-section="sec.id">
                <td class="nowrap"><code>{{ sec.id }}</code></td>
                <td>{{ valueWithUnit(sec.internals) }}<span v-if="sec.internals?.assumed" class="prov assumed" :title="markTitle(sec.internals)">A</span></td>
                <td class="num">{{ valueWithUnit(sec.bottom) }}<span v-if="sec.bottom?.assumed" class="prov assumed" :title="markTitle(sec.bottom)">A</span></td>
                <td class="num">{{ valueWithUnit(sec.height) }}<span v-if="sec.height?.assumed" class="prov assumed" :title="markTitle(sec.height)">A</span></td>
                <td class="num">{{ valueWithUnit(sec.count) }}<span v-if="sec.count?.assumed" class="prov assumed" :title="markTitle(sec.count)">A</span></td>
                <td class="num">{{ valueWithUnit(sec.spacing) }}<span v-if="sec.spacing?.assumed" class="prov assumed" :title="markTitle(sec.spacing)">A</span></td>
                <td class="muted">{{ sec.notes }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="ds.weights" class="weights" data-section="weights" aria-label="Weights">
        <h2>Weights <span class="muted">{{ ds.weights.length }}</span></h2>
        <div class="table-wrap"><table class="data compact">
          <tbody>
            <tr v-for="r in ds.weights" :key="r.key" :data-key="r.key" :class="{ open: r.open === 'tbd', na: r.open === 'not_applicable' }">
              <th scope="row">{{ r.label }}</th>
              <td class="num value">
                <span v-if="r.open === 'tbd'" class="badge error" data-open="tbd" :title="r.source || 'not known yet'">{{ valueText(r) }}</span>
                <span v-else-if="r.open === 'supplier'" class="badge info" data-open="supplier" :title="r.reason || r.source">supplier</span>
                <span v-else-if="r.open === 'not_applicable'" class="badge" data-open="not_applicable" :title="r.reason">n/a</span>
                <template v-else>{{ valueText(r) }}</template>
                <span v-if="r.assumed" class="prov assumed" data-assumed :title="markTitle(r)">A</span>
              </td>
              <td class="unit">{{ r.open ? "" : r.unit }}</td>
              <td class="source"><span :title="r.source">{{ r.reason || r.source }}</span><DatasheetBasis :value="r" /></td>
            </tr>
          </tbody>
        </table></div>
      </section>

      <section v-if="otherTypeSpecific.length" class="other" aria-label="Other type-specific fields">
        <h3>Other type-specific fields</h3>
        <div class="tree-box">
          <JsonTree v-for="[key, value] in otherTypeSpecific" :key="key" :value="value" :name="key" :depth="1" />
        </div>
      </section>

      <section v-if="ds.nozzles.length" class="nozzles" data-section="nozzles">
        <h2>Nozzle schedule <span class="muted">{{ ds.nozzles.length }}</span></h2>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr>
                <th title="The mark on the outline drawing (the P&ID name when not given)">mark</th>
                <th>service</th>
                <th class="num">DN</th>
                <th>rating</th>
                <th>facing</th>
                <th title="top, bottom or side (the shell)">face</th>
                <th class="num" title="Plan direction, deg from site east counter-clockwise">orientation, deg</th>
                <th class="num" title="Nozzle centre above the item's base">elevation, m</th>
                <th class="num" title="Flange face from the item's axis (a side nozzle of a vertical item) or from the surface it leaves">projection, m</th>
                <th>lines</th>
                <th>sheet</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(n, i) in ds.nozzles" :key="`${n.name}-${i}`" :data-nozzle="n.name">
                <td class="nowrap">
                  <code>{{ n.mark }}</code>
                  <span v-if="n.mark !== n.name" class="faint small" :title="`P&ID nozzle ${n.name}`"> ({{ n.name }})</span>
                  <span v-if="n.assumed" class="prov assumed" data-assumed title="assumed: the schedule entry is an assumption">A</span>
                </td>
                <td>{{ n.service }}</td>
                <td class="num">{{ n.dn ?? "" }}</td>
                <td class="nowrap">{{ n.rating }}</td>
                <td class="nowrap" :title="n.standard">{{ n.facing }}<span v-if="n.standard" class="faint small" data-flange-standard> {{ n.standard }}</span></td>
                <td>{{ n.face }}</td>
                <td class="num">{{ fmt(n.orientation_deg, 1) }}</td>
                <td class="num">{{ fmt(n.elevation_m) }}</td>
                <td class="num">{{ fmt(n.projection_m) }}</td>
                <td class="lines">
                  <span v-for="line in n.lines" :key="line" class="line" :data-line="line">
                    <RouterLink v-if="hasLineList" :to="{ name: 'yaml', params: { path: pathSegments(LINE_LIST) }, query: withRev({ filter: line }) }" title="In the line list" data-link="line-list">{{ line }}</RouterLink>
                    <code v-else>{{ line }}</code>
                    <RouterLink v-if="hasLayout" class="small" :to="{ name: 'layout', query: withRev({ select: line }) }" title="Show the line in the 3D layout" data-link="3d">3D</RouterLink>
                  </span>
                </td>
                <td class="nowrap">
                  <RouterLink v-if="sheetLink(n.source)" :to="sheetLink(n.source)!" title="Open the P&ID with the item selected" data-link="pid">{{ sheetTitle(n.source) }}</RouterLink>
                  <span v-else class="muted">{{ n.source }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="ds.nozzles.some((n) => n.location_source)" class="muted small">
          Locations from {{ [...new Set(ds.nozzles.map((n) => n.location_source).filter(Boolean))].join("; ") }}.
        </p>
      </section>

      <section v-if="drawingState" class="drawing" data-section="drawing" aria-label="Outline drawing">
        <h2>
          Outline drawing
          <span class="badge" :class="DRAWING_BADGE[drawingState].cls" :data-drawing-state="drawingState" :title="DRAWING_BADGE[drawingState].title">{{ DRAWING_BADGE[drawingState].text }}</span>
          <span v-if="drawingState === 'stale' && drawing.data.value?.kind === 'generated'" class="badge info" data-drawing-preview>showing the generated preview</span>
        </h2>
        <p class="muted small drawing-note">
          <code>{{ drawingFile }}</code>{{ " " }}
          <template v-if="drawingState === 'missing'">is not committed: this is what <code>cheme datasheets drawing</code> would write.</template>
          <template v-else-if="drawingState === 'stale'">is not what the datasheet gives now.</template>
          <template v-else-if="drawingState === 'unchecked'">(this server does not check whether it is current).</template>
          <template v-else-if="drawingState === 'none'">: the datasheet does not validate, so there is nothing to draw.</template>
          <template v-else>is what the datasheet gives.</template>
        </p>
        <p v-if="drawingState === 'missing' || drawingState === 'stale'" class="hint-cmd" data-drawing-hint>
          Write it: <code>{{ writeHint }}</code>
        </p>
        <div v-if="drawingState !== 'none'" class="toolbar drawing-tools">
          <label v-if="drawingState === 'stale'" class="toggle">
            <input v-model="preview" type="checkbox" data-action="preview" />
            show the drawing the datasheet gives now
          </label>
          <span class="spacer" />
          <a v-if="downloadUrl && drawing.data.value" class="btn" :href="downloadUrl" :download="downloadName" data-action="download-drawing">Download SVG</a>
        </div>
        <p v-if="previewUnavailable" class="notice" data-preview-unavailable>The generated preview is not in this snapshot; this is the committed drawing.</p>
        <p v-if="drawingError" class="notice error" data-drawing-error>{{ drawingError }}</p>
        <SvgPane
          v-if="drawingState !== 'none' && !drawingError"
          class="drawing-pane"
          :layers="layers"
          :view="view"
          :label="`${tag} outline drawing`"
          :empty-text="drawing.loading.value ? 'Loading the drawing…' : 'No drawing.'"
        />
      </section>

      <section class="sizing" data-section="sizing_basis">
        <h2>Sizing basis <span class="muted">{{ ds.sizing_basis.length }}</span></h2>
        <ul v-if="ds.sizing_basis.length">
          <li v-for="(item, i) in ds.sizing_basis" :key="i">
            <strong>{{ item.parameter }}</strong>:
            <span :class="{ bad: item.open === 'tbd' }">{{ valueText(item) }}</span><template v-if="item.unit"> {{ item.unit }}</template>
            <span v-if="item.assumed" class="prov assumed" :title="markTitle(item)">A</span>
            <span v-if="item.reference" class="muted"> ({{ item.reference }})</span>
            <DatasheetBasis :value="item" />
          </li>
        </ul>
        <p v-else class="muted">None recorded yet.</p>
      </section>

      <section v-if="ds.notes" class="notes">
        <h2>Notes</h2>
        <p>{{ ds.notes }}</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.crumbs {
  margin: 0 0 var(--space-2);
  font-size: var(--text-sm);
}
.service {
  margin: -4px 0 var(--space-3);
  color: var(--fg-muted);
}
.summary {
  font-size: var(--text-sm);
}
.summary strong {
  font-weight: 600;
}
h2 {
  font-size: var(--text);
  margin: var(--space-4) 0 var(--space-2);
}
h2 .muted {
  font-weight: normal;
  font-size: var(--text-sm);
}
h3 {
  font-size: var(--text-sm);
  margin: var(--space-3) 0 var(--space-1);
}
.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.nowrap {
  white-space: nowrap;
}
.param code {
  white-space: nowrap;
}
.value .prov {
  margin-left: 4px;
  cursor: help;
}
.unit {
  white-space: nowrap;
  color: var(--fg-muted);
}
.source {
  color: var(--fg-muted);
  min-width: 240px;
  overflow-wrap: anywhere;
}
.reason {
  display: block;
  color: var(--fg);
}
tr.open td {
  background: var(--bad-soft);
}
tr.na td {
  color: var(--fg-faint);
}
.warn {
  color: var(--warn);
}
.bad {
  color: var(--bad);
}
.lines {
  min-width: 120px;
}
.line {
  display: inline-flex;
  gap: 4px;
  align-items: baseline;
  margin-right: var(--space-2);
  white-space: nowrap;
}
.small {
  font-size: 11.5px;
}
p.small {
  font-size: var(--text-sm);
  margin: var(--space-1) 0 0;
}
.tree-box {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
}
.sizing ul {
  margin: 0;
  padding-left: var(--space-4);
  font-size: var(--text-sm);
}
.sizing li + li {
  margin-top: 2px;
}
.notes p {
  margin: 0;
  white-space: pre-wrap;
  font-size: var(--text-sm);
  max-width: 100ch;
}
.value.mat {
  white-space: normal;
  text-align: left;
}
.chip {
  display: block;
  width: fit-content;
  margin-top: 2px;
  font-weight: 500;
}
.standard {
  color: var(--fg-muted);
  white-space: nowrap;
}
.dim-groups {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: var(--space-2) var(--space-4);
}
.dim-group h3,
.col-sections h3 {
  margin-top: 0;
}
/* Fixed columns, so a long source is cut (in full in its title) instead of widening the group. */
table.compact {
  width: 100%;
  table-layout: fixed;
}
table.compact th[scope="row"] {
  width: 36%;
  font-weight: 500;
  text-align: left;
  overflow-wrap: anywhere;
}
table.compact .value {
  width: 24%;
  overflow-wrap: anywhere;
}
table.compact .unit {
  width: 12%;
}
table.compact .source {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11.5px;
}
.weights table.compact {
  max-width: 720px;
}
.col-sections {
  margin-top: var(--space-3);
}
.drawing h2 .badge {
  margin-left: var(--space-1);
  vertical-align: 2px;
}
.drawing-note {
  margin: 0 0 var(--space-1);
}
.hint-cmd {
  margin: 0 0 var(--space-2);
  font-size: var(--text-sm);
}
.drawing-tools {
  margin-bottom: var(--space-2);
}
.toggle {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  font-size: var(--text-sm);
}
.drawing-pane {
  height: min(70vh, 640px);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}
@media (max-width: 640px) {
  .source {
    min-width: 180px;
  }
  .dim-groups {
    grid-template-columns: minmax(0, 1fr);
  }
  .drawing-pane {
    height: 60vh;
  }
}
</style>
