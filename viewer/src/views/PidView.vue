<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { api } from "@/api";
import SvgPane, { type Picked } from "@/components/SvgPane.vue";
import InfoPanel from "@/components/InfoPanel.vue";
import LoadState from "@/components/LoadState.vue";
import { sanitizeSvg } from "@/lib/sanitize";
import { createView } from "@/lib/panzoom";
import { cssString, selectionCss } from "@/lib/highlight";
import { findTagGroup } from "@/lib/pidTag";
import { signalEmbed, signalEmbedSelection } from "@/lib/embedSignal";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { paramPath, pathSegments, shortRev } from "@/lib/format";
import { store, useIssues } from "@/store";
import { newIssueUrl, objectTag } from "@/lib/issues";
import ProcessPanel from "@/components/ProcessPanel.vue";
import { KIND_BADGE, isProcessSheet } from "@/lib/process";
import { drawingFileName, drawingPdf, saveBlob } from "@/lib/pdfExport";

const route = useRoute();
const { rev, withRev } = useRev();
const path = computed(() => paramPath(route.params.path));
const view = createView();
const picked = ref<Picked | null>(null);
const pane = ref<InstanceType<typeof SvgPane> | null>(null);

const svg = useAsync(async (signal) => sanitizeSvg(await api.pidSvg(path.value, rev.value, signal)), [path, rev]);
watch(picked, (object) => signalEmbedSelection(object?.id ?? null));
// The embedding page learns when the drawing is on screen, or that it will not come.
watch(
  [svg.data, svg.error],
  ([data, error]) => {
    if (data) signalEmbed("visual");
    else if (error) signalEmbed("error");
  },
  { flush: "post" },
);
// The picked object (its labels) belongs to the drawing it was picked in; `?select=` picks again.
watch([path, rev], () => (picked.value = null));

const sheet = computed(() => store.repo?.sheets.find((s) => s.file === path.value));
const isProcess = computed(() => isProcessSheet(sheet.value));
// BFD/PFD: the stream table answers what a picked connection, stream or block carries.
const streams = useAsync(
  async (signal) => (isProcess.value ? api.streams({ rev: rev.value }, signal) : null),
  [isProcess, rev],
);
const layers = computed(() => [{ id: "pid-layer", svg: svg.data.value }]);
const css = computed(() => selectionCss("pid-layer", picked.value?.id ?? null));
/**
 * `?select=<id>` (from the layout's "Open in P&ID"): pick and centre that object once drawn. A
 * printed tag (`?select=LIA-4107`, from the cause & effect matrix) picks the object drawn for it.
 */
const selectParam = computed(() => {
  const value = route.query.select;
  const first = Array.isArray(value) ? value[0] : value;
  return first ? String(first) : null;
});
watch(
  () => [svg.data.value, selectParam.value] as const,
  async ([drawing, id]) => {
    if (!drawing || !id) return;
    // After the pane mounted and fitted the new drawing.
    await nextTick();
    await nextTick();
    const layer = document.querySelector('[id="pid-layer"]');
    const el = layer?.querySelector(`[id="${cssString(id)}"]`) ?? (layer ? findTagGroup(layer, id) : null);
    const target = el?.id || id;
    const texts = el ? [...new Set(Array.from(el.querySelectorAll("text"), (t) => (t.textContent ?? "").trim()).filter(Boolean))] : [];
    picked.value = { id: target, layer: "pid-layer", className: el?.getAttribute("class") ?? "", texts: texts.slice(0, 20) };
    selectedBy.value = { id: target, tag: id };
    pane.value?.focus(target);
  },
  { flush: "post" },
);
/** The object `?select=` picked and the tag it was asked for by, for the issue references. */
const selectedBy = ref<{ id: string; tag: string } | null>(null);
const issues = useIssues();
/** "New issue about <tag>": the action-item form with References "<sheet id> <tag>". */
const issueLink = computed(() => {
  const item = picked.value;
  if (!item || !issues.value) return null;
  const tag = objectTag(item, selectedBy.value?.id === item.id ? selectedBy.value.tag : null);
  const url = newIssueUrl(issues.value, { refs: `${sheet.value?.id ?? path.value} ${tag}` });
  return url ? { url, tag } : null;
});
const layoutLink = computed(() => (picked.value && store.repo?.has_layout ? { name: "layout", query: withRev({ select: picked.value.id }) } : null));
/**
 * "PDF" and "SVG": the drawing at the revision shown, as the API served it and cleaned (never the
 * pane's DOM, so no selection or highlight), named `<plant>-<sheet>[-<rev>]`.
 */
const exporting = ref(false);
const exportError = ref<string | null>(null);
watch([path, rev], () => (exportError.value = null));
function fileName(ext: "pdf" | "svg"): string {
  const shown = rev.value ?? store.snapshot?.commit ?? null;
  return drawingFileName({ plant: store.repo?.name || store.repo?.root_name, sheet: sheet.value?.id, path: path.value, rev: shown ? shortRev(shown) : null, ext });
}
async function downloadPdf(): Promise<void> {
  const drawing = svg.data.value;
  if (!drawing || exporting.value) return;
  exporting.value = true;
  exportError.value = null;
  try {
    const title = sheet.value ? `${sheet.value.id} ${sheet.value.title}`.trim() : path.value;
    const plant = store.repo?.name || store.repo?.root_name || "";
    const at = rev.value ? shortRev(rev.value) : store.snapshot?.commit ? shortRev(store.snapshot.commit) : "working tree";
    const name = fileName("pdf");
    saveBlob(await drawingPdf(drawing.element, { title, subject: `${plant ? `${plant}, ` : ""}${path.value} at ${at}` }), name);
  } catch (error) {
    exportError.value = `Cannot make the PDF: ${error instanceof Error ? error.message : String(error)}`;
  } finally {
    exporting.value = false;
  }
}
function downloadSvg(): void {
  const drawing = svg.data.value;
  if (drawing) saveBlob(new Blob([drawing.markup], { type: "image/svg+xml" }), fileName("svg"));
}
const diffQuery = computed(() => (rev.value ? { old: rev.value, rev: rev.value } : { old: "HEAD" }));
</script>

<template>
  <div class="pid">
    <div class="bar">
      <h1>
        <span v-if="sheet">{{ sheet.id }} <span class="muted">{{ sheet.title }}</span></span>
        <span v-else>{{ path }}</span>
        <span v-if="sheet?.kind && sheet.kind !== 'pid'" class="badge stage">{{ KIND_BADGE[sheet.kind] }}</span>
        <small>{{ shortRev(rev) }}</small>
      </h1>
      <div class="actions">
        <RouterLink v-if="layoutLink" class="btn" :to="layoutLink" title="Show the selected object in the 3D layout" data-action="show-3d">Show in 3D</RouterLink>
        <RouterLink v-if="isProcess" class="btn" :to="{ name: 'streams', query: withRev() }">Stream table</RouterLink>
        <RouterLink class="btn" :to="{ name: 'file', params: { path: pathSegments(path) }, query: withRev() }">XML</RouterLink>
        <button
          type="button"
          class="btn"
          data-action="download-pdf"
          :disabled="!svg.data.value || exporting"
          :aria-busy="exporting"
          :aria-label="exporting ? 'Making the PDF of this drawing' : 'Download this drawing as PDF'"
          title="Download this drawing as a vector PDF (ISO A sheet)"
          @click="downloadPdf"
        >
          {{ exporting ? "PDF…" : "PDF" }}
        </button>
        <button
          type="button"
          class="btn"
          data-action="download-svg"
          :disabled="!svg.data.value"
          aria-label="Download this drawing as SVG"
          title="Download this drawing as SVG"
          @click="downloadSvg"
        >
          SVG
        </button>
        <RouterLink v-if="!store.snapshot" class="btn" :to="{ name: 'history', query: withRev({ path }) }">History</RouterLink>
        <RouterLink
          v-if="!store.snapshot"
          class="btn"
          :to="{ name: 'diff', params: { path: pathSegments(path) }, query: diffQuery }"
          :title="rev ? `Compare ${rev} with the working tree` : 'Compare HEAD with the working tree'"
        >
          Diff
        </RouterLink>
      </div>
    </div>
    <div class="body">
      <LoadState class="state" :loading="svg.loading.value && !svg.data.value" :error="svg.error.value" @retry="svg.reload" />
      <div v-if="exportError" class="notice error state" role="alert" data-testid="export-error">
        {{ exportError }}
        <button type="button" class="btn" aria-label="Dismiss" @click="exportError = null">Dismiss</button>
      </div>
      <SvgPane
        ref="pane"
        class="canvas"
        :layers="layers"
        :view="view"
        :css="css"
        :empty-text="svg.loading.value ? 'Rendering…' : 'Nothing to draw.'"
        @pick="picked = $event"
      />
      <ProcessPanel
        v-if="isProcess"
        :picked="picked"
        :table="streams.data.value ?? null"
        :sheet-kind="sheet?.kind"
        :error="streams.error.value"
        :issue="issueLink"
        @close="picked = null"
      />
      <InfoPanel v-else :picked="picked" :issue="issueLink" @close="picked = null" />
    </div>
  </div>
</template>

<style scoped>
.pid {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2) var(--space-4);
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--border);
}
h1 {
  font-size: var(--text-lg);
  margin: 0;
  display: flex;
  gap: var(--space-2);
  align-items: baseline;
  min-width: 0;
  word-break: break-all;
}
h1 small {
  color: var(--fg-muted);
  font-weight: normal;
  font-size: var(--text-sm);
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  margin-left: auto;
}
.actions .btn:hover {
  text-decoration: none;
}
.body {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
}
.canvas {
  flex: 1;
}
.state {
  position: absolute;
  top: 8px;
  left: 8px;
  right: 8px;
  z-index: 4;
}
</style>
