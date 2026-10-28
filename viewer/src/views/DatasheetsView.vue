<script setup lang="ts">
import { computed, ref } from "vue";
import LoadState from "@/components/LoadState.vue";
import { whenRepo } from "@/store";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { shortRev } from "@/lib/format";
import { DATASHEET_DIR } from "@/lib/studies";
import {
  drawingState,
  entryDraft,
  entryHasDimensions,
  entryHasWeights,
  entryService,
  entryType,
  filterEntries,
  loadDatasheetIndex,
  serverHasDatasheets,
  sortEntries,
  totalsOf,
  type DatasheetIndexView,
  type SortKey,
} from "@/lib/datasheets";
import type { DrawingState } from "@/api";

const { rev, withRev } = useRev();

// `/api/datasheets` when the server has it; else the tree names the files and `/api/yaml` reads each one.
const index = useAsync<DatasheetIndexView>(async (signal) => loadDatasheetIndex(rev.value, serverHasDatasheets(await whenRepo()), signal), rev);
const all = computed(() => index.data.value?.entries ?? []);
const missing = computed(() => index.data.value?.missing ?? []);
const fromServer = computed(() => index.data.value?.source === "server");

const query = ref("");
const type = ref("");
const sortKey = ref<SortKey>("tag");
const sortDir = ref<1 | -1>(1);
const types = computed(() => [...new Set(all.value.map(entryType).filter((t): t is string => Boolean(t)))].sort());
const shown = computed(() => sortEntries(filterEntries(all.value, query.value, type.value), sortKey.value, sortDir.value));
const totals = computed(() => totalsOf(all.value));

const COLUMNS: { key: SortKey; label: string; num?: boolean; title?: string; server?: boolean }[] = [
  { key: "tag", label: "tag" },
  { key: "type", label: "type" },
  { key: "service", label: "service" },
  { key: "draft", label: "status", title: "draft: a generated sheet the datasheets gate does not count yet" },
  { key: "assumed", label: "assumed", num: true, title: "Values marked assumed: true (confirm them)" },
  { key: "tbd", label: "TBD", num: true, title: "Values not known yet: TBD, null or missing" },
  { key: "dimensions", label: "dimensions", title: "The sheet states its main dimensions (cheme datasheets fill --dimensions)" },
  { key: "weights", label: "weights", title: "The sheet states its weights (empty, operating, test)" },
  { key: "drawing", label: "drawing", title: "The outline drawing equipment/datasheets/<TAG>.svg: current, stale or missing", server: true },
  { key: "findings", label: "findings", title: "Findings on the sheet and its drawing (errors, warnings)", server: true },
];
const columns = computed(() => COLUMNS.filter((c) => !c.server || fromServer.value));
const DESCENDING: SortKey[] = ["assumed", "tbd", "draft", "drawing", "findings"];

function sortBy(key: SortKey): void {
  if (sortKey.value === key) sortDir.value = sortDir.value === 1 ? -1 : 1;
  else {
    sortKey.value = key;
    // Counts and problems read best largest first.
    sortDir.value = DESCENDING.includes(key) ? -1 : 1;
  }
}
const ariaSort = (key: SortKey) => (sortKey.value === key ? (sortDir.value === 1 ? "ascending" : "descending") : "none");

const DRAWING_BADGE: Record<DrawingState, { cls: string; text: string; title: string }> = {
  current: { cls: "clean", text: "current", title: "The committed drawing is what the datasheet gives now" },
  stale: { cls: "warning", text: "stale", title: "The committed drawing is not what the datasheet gives now: cheme datasheets drawing --write" },
  missing: { cls: "error", text: "missing", title: "No drawing committed: cheme datasheets drawing --write" },
  none: { cls: "", text: "none", title: "The datasheet does not validate, so there is no drawing" },
};
</script>

<template>
  <div class="page datasheets">
    <h1>
      Equipment datasheets
      <small>{{ DATASHEET_DIR }}/{{ rev ? ` at ${shortRev(rev)}` : " in the working tree" }}</small>
    </h1>
    <p class="muted hint">
      One sheet per equipment-list item (<code>cheme datasheets draft</code> / <code>fill</code>). Every value says where it comes
      from; assumed values are to be confirmed, TBD ones are not known yet, and a draft is not counted by the datasheets gate.
    </p>

    <LoadState :loading="index.loading.value && !index.data.value" :error="index.error.value" @retry="index.reload" />

    <template v-if="index.data.value">
      <p v-if="!all.length" class="notice" data-empty>No datasheets in <code>{{ DATASHEET_DIR }}/</code> at this revision.</p>
      <template v-else>
        <div class="cards" aria-label="Totals">
          <div class="card"><span class="card-title">sheets</span><span class="card-value" data-total="sheets">{{ totals.sheets }}</span></div>
          <div class="card"><span class="card-title">drafts</span><span class="card-value" data-total="drafts">{{ totals.drafts }}</span></div>
          <div class="card"><span class="card-title">assumed values</span><span class="card-value" data-total="assumed">{{ totals.assumed }}</span></div>
          <div class="card"><span class="card-title">TBD or missing</span><span class="card-value" data-total="tbd">{{ totals.tbd }}</span></div>
          <div class="card"><span class="card-title">awaiting supplier</span><span class="card-value" data-total="supplier">{{ totals.supplier }}</span></div>
          <div class="card"><span class="card-title">with dimensions</span><span class="card-value" data-total="dimensions">{{ totals.dimensions }}</span></div>
          <div class="card"><span class="card-title">with weights</span><span class="card-value" data-total="weights">{{ totals.weights }}</span></div>
          <template v-if="fromServer">
            <div class="card" title="Outline drawings that are what the datasheets give now">
              <span class="card-title">drawings current</span><span class="card-value" data-total="drawings-current">{{ totals.drawings.current }}</span>
            </div>
            <div class="card" title="Stale or missing outline drawings: cheme datasheets drawing --write">
              <span class="card-title">drawings stale / missing</span>
              <span class="card-value" data-total="drawings-open"><span :class="{ warn: totals.drawings.stale }">{{ totals.drawings.stale }}</span> / <span :class="{ bad: totals.drawings.missing }">{{ totals.drawings.missing }}</span></span>
            </div>
            <div class="card" title="Findings on the datasheets and their drawings">
              <span class="card-title">errors / warnings</span>
              <span class="card-value" data-total="findings"><span :class="{ bad: totals.findings.error }">{{ totals.findings.error }}</span> / <span :class="{ warn: totals.findings.warning }">{{ totals.findings.warning }}</span></span>
            </div>
            <div class="card" title="Equipment-list items without a datasheet">
              <span class="card-title">items without a sheet</span><span class="card-value" :class="{ bad: missing.length }" data-total="missing">{{ missing.length }}</span>
            </div>
          </template>
        </div>

        <div class="toolbar">
          <input v-model="query" type="search" placeholder="Filter by tag, type or service" aria-label="Filter datasheets" />
          <label class="sr-only" for="ds-type">Type</label>
          <select id="ds-type" v-model="type" aria-label="Type">
            <option value="">all types</option>
            <option v-for="t in types" :key="t" :value="t">{{ t }}</option>
          </select>
          <span class="muted count">{{ shown.length }} of {{ all.length }}</span>
        </div>

        <div class="table-wrap">
          <table class="data" aria-label="Datasheets">
            <thead>
              <tr>
                <th v-for="c in columns" :key="c.key" :class="{ num: c.num }" :aria-sort="ariaSort(c.key)" :title="c.title">
                  <button type="button" class="sort" :data-sort="c.key" @click="sortBy(c.key)">
                    {{ c.label }}<span class="faint" aria-hidden="true">{{ sortKey === c.key ? (sortDir === 1 ? " ▲" : " ▼") : "" }}</span>
                  </button>
                </th>
                <th class="num" title="Waiting for the supplier's data">supplier</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="e in shown" :key="e.tag" :data-tag="e.tag">
                <td class="nowrap">
                  <RouterLink :to="{ name: 'datasheet', params: { tag: e.tag }, query: withRev() }">{{ e.tag }}</RouterLink>
                </td>
                <template v-if="e.sheet || e.summary">
                  <td>{{ entryType(e) ?? "" }}</td>
                  <td>{{ entryService(e) }}</td>
                  <td>
                    <span v-if="e.error" class="badge error" data-invalid :title="e.error">invalid</span>
                    <span v-else-if="entryDraft(e)" class="badge warning" data-draft>draft</span>
                    <span v-else class="badge clean">final</span>
                  </td>
                  <td class="num" :class="{ warn: e.counts?.assumed }">{{ e.counts?.assumed }}</td>
                  <td class="num" :class="{ bad: e.counts?.tbd }">{{ e.counts?.tbd }}</td>
                  <td data-col="dimensions"><span v-if="entryHasDimensions(e)" class="badge info" data-has="dimensions">stated</span><span v-else class="faint">–</span></td>
                  <td data-col="weights"><span v-if="entryHasWeights(e)" class="badge info" data-has="weights">stated</span><span v-else class="faint">–</span></td>
                  <template v-if="fromServer">
                    <td data-col="drawing">
                      <span v-if="drawingState(e.summary)" class="badge" :class="DRAWING_BADGE[drawingState(e.summary)!].cls" :data-drawing="drawingState(e.summary)" :title="DRAWING_BADGE[drawingState(e.summary)!].title">{{ DRAWING_BADGE[drawingState(e.summary)!].text }}</span>
                    </td>
                    <td data-col="findings" class="nowrap">
                      <template v-if="e.summary">
                        <span v-if="e.summary.findings.error" class="badge error" data-findings="error" :title="`${e.summary.findings.error} errors`">{{ e.summary.findings.error }} E</span>
                        <span v-if="e.summary.findings.warning" class="badge warning" data-findings="warning" :title="`${e.summary.findings.warning} warnings`">{{ e.summary.findings.warning }} W</span>
                        <span v-if="e.summary.findings.info" class="badge info" data-findings="info" :title="`${e.summary.findings.info} infos`">{{ e.summary.findings.info }} I</span>
                        <span v-if="!e.summary.findings.error && !e.summary.findings.warning && !e.summary.findings.info" class="faint">–</span>
                      </template>
                    </td>
                  </template>
                  <td class="num">{{ e.counts?.supplier || "" }}</td>
                </template>
                <td v-else :colspan="columns.length" class="bad">{{ e.error }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!shown.length" class="muted">No datasheet matches.</p>
        <p v-if="!fromServer" class="muted small" data-tree-source>
          This server lists the datasheets from the files (an older <code>cheme serve</code> or a snapshot without <code>/api/datasheets</code>): drawing states and findings are not shown.
        </p>
      </template>
      <section v-if="missing.length" class="missing" aria-label="Items without a datasheet" data-missing-tags>
        <h2>Items without a datasheet <span class="muted">{{ missing.length }}</span></h2>
        <p class="muted small">In the equipment list, no <code>{{ DATASHEET_DIR }}/&lt;TAG&gt;.yaml</code>: <code>cheme datasheets draft</code> writes a draft for each.</p>
        <ul>
          <li v-for="t in missing" :key="t" :data-missing-tag="t"><code>{{ t }}</code> <span class="faint">cheme datasheets draft --tag {{ t }}</span></li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.hint {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
  max-width: 80ch;
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}
.card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  font-size: var(--text-sm);
}
.card-title {
  color: var(--fg-muted);
}
.card-value {
  font-size: var(--text-lg);
  font-variant-numeric: tabular-nums;
}
.toolbar input[type="search"] {
  min-width: 240px;
  flex: 1 1 240px;
  max-width: 420px;
}
.count {
  font-size: var(--text-sm);
}
.sort {
  border: 0;
  background: none;
  padding: 0;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
th.num .sort {
  text-align: right;
}
.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.nowrap {
  white-space: nowrap;
}
.warn {
  color: var(--warn);
  font-weight: 600;
}
.bad {
  color: var(--bad);
  font-weight: 600;
}
.small {
  font-size: var(--text-sm);
}
td .badge + .badge {
  margin-left: 2px;
}
.missing h2 {
  font-size: var(--text);
  margin: var(--space-4) 0 var(--space-1);
}
.missing ul {
  margin: var(--space-1) 0 0;
  padding-left: var(--space-4);
  font-size: var(--text-sm);
}
@media (max-width: 640px) {
  .toolbar input[type="search"] {
    min-width: 0;
    max-width: none;
  }
}
</style>
