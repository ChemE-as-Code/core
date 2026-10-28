<script setup lang="ts">
import { computed, ref } from "vue";
import { api, ApiError, type Commit, type InterlockMatrix } from "@/api";
import LoadState from "@/components/LoadState.vue";
import { store } from "@/store";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { pathSegments, shortRev } from "@/lib/format";
import { actionTone, cellActions, cellKey, cellTone, compareMatrix, INTERLOCKS_FILE, matrixCsv, tagSheets, type RowField } from "@/lib/causeEffect";

const { rev, withRev } = useRev();

/** The matrix at `rev`, or null when there is no `control/cause-effect.yaml` there (a 404). */
async function load(at: string | null | undefined, signal: AbortSignal): Promise<InterlockMatrix | null> {
  try {
    return await api.interlocks(at, signal);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

const matrix = useAsync((signal) => load(rev.value, signal), rev);
const data = computed(() => matrix.data.value ?? null);
const missing = computed(() => !matrix.loading.value && !matrix.error.value && matrix.data.value === null);
const sheets = computed(() => (data.value ? tagSheets(data.value, store.repo?.sheets ?? []) : new Map<string, string>()));
const notes = computed(() => data.value?.interlocks.filter((i) => i.notes.trim()) ?? []);

/** Link to the P&ID drawing `tag`, selected; null when the list names no sheet for it. */
function pidLink(tag: string) {
  const file = sheets.value.get(tag);
  return file ? { name: "pid", params: { path: pathSegments(file) }, query: withRev({ select: tag }) } : null;
}

// -- another revision, for comparison (a server only: a snapshot holds one revision) -------------
const other = ref("");
const commits = useAsync<Commit[]>(
  (signal) => (store.snapshot ? Promise.resolve([]) : api.log({ limit: 20, path: INTERLOCKS_FILE, rev: rev.value }, signal).catch(() => [])),
  rev,
);
const otherMatrix = useAsync((signal) => (other.value ? load(other.value, signal) : Promise.resolve(null)), other);
/** The other revision's matrix, only once it is the one asked for (not a previous one while loading). */
const otherData = computed(() => (other.value && !otherMatrix.loading.value ? (otherMatrix.data.value ?? null) : null));
const otherError = computed(() => (other.value && !otherMatrix.loading.value ? otherMatrix.error.value : null));
const diff = computed(() => (data.value && otherData.value ? compareMatrix(data.value, otherData.value) : null));
const changedCells = computed(() => diff.value?.cells.size ?? 0);

const FIELD_LABEL: Record<RowField, string> = { title: "title", cause: "cause", condition: "condition", sheet: "sheet", sil: "SIL" };
function changed(row: string, field: RowField): boolean {
  return diff.value?.changedFields.get(row)?.includes(field) ?? false;
}
function rowChanges(row: string): string {
  const fields = diff.value?.changedFields.get(row);
  return fields ? `changed since ${other.value}: ${fields.map((f) => FIELD_LABEL[f]).join(", ")}` : "";
}
/** The other revision's action(s) in a changed cell ("" when it had none), or undefined when unchanged. */
function before(row: string, column: string): string | undefined {
  return diff.value?.cells.get(cellKey(row, column));
}

const silText = (sil: string | number | null) => (sil === null || sil === undefined || sil === "" ? "" : String(sil));

function downloadCsv(): void {
  if (!data.value) return;
  const url = URL.createObjectURL(new Blob([matrixCsv(data.value)], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `cause-effect${rev.value ? `-${shortRev(rev.value)}` : ""}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
</script>

<template>
  <div class="page ce">
    <h1>
      Cause &amp; effect
      <small>{{ INTERLOCKS_FILE }}{{ rev ? ` at ${shortRev(rev)}` : " in the working tree" }}</small>
    </h1>

    <LoadState :loading="matrix.loading.value && !data" :error="matrix.error.value" @retry="matrix.reload" />
    <div v-if="missing" class="notice" data-ce-missing>
      <p><strong>No interlocks{{ rev ? ` at ${shortRev(rev)}` : "" }}.</strong></p>
      <p class="muted">The page shows <code>{{ INTERLOCKS_FILE }}</code> as <code>cheme cause-effect</code> draws it: each interlock's cause (an instrument tag and its condition) and its effects (a tag and an action each). Schema: <code>cheme schema interlocks</code>.</p>
    </div>

    <template v-if="data">
      <div class="toolbar">
        <label v-if="!store.snapshot" class="compare-select">
          Compare with
          <select v-model="other" data-action="compare">
            <option value="">none</option>
            <optgroup v-if="store.branches.length" label="Branches">
              <option v-for="b in store.branches" :key="b.name" :value="b.name">{{ b.name }}</option>
            </optgroup>
            <optgroup v-if="commits.data.value?.length" :label="`Commits changing ${INTERLOCKS_FILE}`">
              <option v-for="c in commits.data.value" :key="c.sha" :value="c.sha">{{ c.short }} {{ c.subject }}</option>
            </optgroup>
          </select>
        </label>
        <span class="spacer" />
        <span class="legend" aria-label="Actions">
          <span class="chip tone-stop">trip / stop / close</span>
          <span class="chip tone-start">open / start</span>
          <span class="chip tone-alarm">alarm</span>
        </span>
        <button type="button" class="btn" data-action="ce-csv" title="The matrix as cheme cause-effect writes it (build/cause-effect.csv)" @click="downloadCsv">CSV</button>
      </div>

      <p v-if="other && otherMatrix.loading.value" class="muted">Loading {{ other }}&hellip;</p>
      <p v-else-if="otherError" class="notice warning" data-compare-error>The interlocks at {{ other }} do not load: {{ otherError }}</p>
      <p v-else-if="other && !otherData" class="muted" data-compare-summary>No interlocks at {{ other }}: every one is new.</p>
      <p v-else-if="diff" class="compare-summary" data-compare-summary>
        <template v-if="diff.same">Same as {{ other }}.</template>
        <template v-else>
          Against {{ other }}:
          {{ changedCells }} cell{{ changedCells === 1 ? "" : "s" }} changed<template v-if="diff.addedRows.size">, {{ diff.addedRows.size }} interlock{{ diff.addedRows.size === 1 ? "" : "s" }} added</template><template v-if="diff.changedFields.size">, {{ diff.changedFields.size }} with changed cause or details</template><template v-if="diff.removedRows.length">, {{ diff.removedRows.length }} removed</template>.
        </template>
      </p>

      <p v-if="!data.rows.length" class="muted">{{ data.file }} lists no interlocks.</p>
      <div v-else class="table-wrap matrix-wrap">
        <table class="matrix" aria-label="Cause and effect matrix">
          <thead>
            <tr>
              <th class="sticky c-id" scope="col">Interlock</th>
              <th class="sticky c-cause" scope="col">Cause</th>
              <th class="c-sil" scope="col">SIL</th>
              <th v-for="tag in data.columns" :key="tag" class="effect" scope="col" :data-column="tag">
                <span class="vertical">
                  <RouterLink v-if="pidLink(tag)" :to="pidLink(tag)!" :title="`Show ${tag} on its P&ID`">{{ tag }}</RouterLink>
                  <span v-else>{{ tag }}</span>
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in data.rows" :key="row.id" :data-row="row.id" :class="{ added: diff?.addedRows.has(row.id) }" :title="diff?.addedRows.has(row.id) ? `not at ${other}` : rowChanges(row.id)">
              <th class="sticky c-id" scope="row">
                <strong>{{ row.id }}</strong>
                <span class="title" :class="{ changed: changed(row.id, 'title') }">{{ row.title }}</span>
              </th>
              <td class="sticky c-cause">
                <RouterLink v-if="pidLink(row.cause)" class="tag" :class="{ changed: changed(row.id, 'cause') }" :to="pidLink(row.cause)!" :title="`Show ${row.cause} on ${row.sheet}`">{{ row.cause }}</RouterLink>
                <code v-else class="tag" :class="{ changed: changed(row.id, 'cause') }">{{ row.cause }}</code>
                <span v-if="row.condition" class="badge condition" :class="{ changed: changed(row.id, 'condition') }">{{ row.condition }}</span>
                <span v-if="row.sheet" class="sheet faint" :class="{ changed: changed(row.id, 'sheet') }">{{ row.sheet }}</span>
              </td>
              <td class="c-sil" :class="{ changed: changed(row.id, 'sil') }">{{ silText(row.sil) || "–" }}</td>
              <td
                v-for="(action, i) in row.cells"
                :key="data.columns[i]"
                class="cell"
                :class="[cellTone(action) ? `tone-${cellTone(action)}` : '', { changed: before(row.id, data.columns[i]!) !== undefined, multi: cellActions(action).length > 1 }]"
                :data-cell="`${row.id}|${data.columns[i]}`"
                :title="before(row.id, data.columns[i]!) !== undefined ? `${other}: ${before(row.id, data.columns[i]!) || 'none'}` : `${row.cause} ${row.condition}: ${action || 'no action on'} ${data.columns[i]}`"
              >
                <template v-if="cellActions(action).length > 1">
                  <span v-for="(a, j) in cellActions(action)" :key="j" class="chip action" :class="`tone-${actionTone(a)}`" data-action-chip>{{ a }}</span>
                </template>
                <template v-else>{{ action }}</template>
                <del v-if="before(row.id, data.columns[i]!)" class="was">{{ before(row.id, data.columns[i]!) }}</del>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <section v-if="diff && (diff.removedRows.length || diff.removedCells.length)" class="removed" aria-label="Removed" data-compare-removed>
        <h2>Only at {{ other }}</h2>
        <ul>
          <li v-for="r in diff.removedRows" :key="r.id">
            <strong>{{ r.id }}</strong> {{ r.title }}: <code>{{ r.cause }}</code> {{ r.condition }}
          </li>
          <li v-for="c in diff.removedCells" :key="`${c.row}|${c.column}`">
            <strong>{{ c.row }}</strong>: {{ c.action }} <code>{{ c.column }}</code>
          </li>
        </ul>
      </section>

      <section v-if="notes.length" class="notes" aria-label="Notes">
        <h2>Notes</h2>
        <dl>
          <template v-for="i in notes" :key="i.id">
            <dt>{{ i.id }}</dt>
            <dd>{{ i.notes }}</dd>
          </template>
        </dl>
      </section>
    </template>
  </div>
</template>

<style scoped>
.ce {
  --ce-id-w: 11rem;
}
.compare-select {
  display: inline-flex;
  gap: var(--space-1);
  align-items: center;
  font-size: var(--text-sm);
  color: var(--fg-muted);
}
.compare-select select {
  max-width: 320px;
}
.legend {
  display: inline-flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  font-size: var(--text-sm);
}
.chip {
  padding: 1px 8px;
  border-radius: 999px;
}
.compare-summary {
  font-size: var(--text-sm);
  margin: 0 0 var(--space-2);
}
/* The wrap scrolls both ways, so the header row and the first two columns stay in view. */
.matrix-wrap {
  max-height: calc(100dvh - var(--header-h) - 150px);
  min-height: 200px;
}
.matrix {
  border-collapse: separate;
  border-spacing: 0;
  font-size: var(--text-sm);
}
.matrix th,
.matrix td {
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
  border-right: 1px solid var(--border);
  text-align: left;
  vertical-align: middle;
  background: var(--surface);
}
.matrix thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--bg-soft);
  font-weight: 600;
  vertical-align: bottom;
  white-space: nowrap;
}
.matrix .sticky {
  position: sticky;
  z-index: 1;
}
.matrix thead .sticky {
  z-index: 3;
}
.matrix .c-id {
  left: 0;
  width: var(--ce-id-w);
  min-width: var(--ce-id-w);
  max-width: var(--ce-id-w);
}
.matrix .c-cause {
  left: var(--ce-id-w);
  white-space: nowrap;
  box-shadow: 2px 0 0 var(--border);
}
.matrix tbody th {
  font-weight: normal;
}
.c-id strong {
  display: block;
}
.c-id .title {
  display: block;
  color: var(--fg-muted);
  white-space: normal;
}
.c-cause .tag {
  font-family: var(--mono);
  font-weight: 600;
}
.c-cause .condition {
  margin-left: var(--space-1);
}
.c-cause .sheet {
  display: block;
  font-size: 11px;
}
.c-sil {
  text-align: center;
  color: var(--fg-muted);
}
.effect {
  text-align: center;
  height: 7.5rem;
  padding: 6px 4px;
}
.effect .vertical {
  writing-mode: vertical-rl;
  transform: rotate(180deg);
  font-family: var(--mono);
}
.cell {
  text-align: center;
  min-width: 3.6rem;
  white-space: nowrap;
}
.tone-stop {
  background: var(--bad-soft);
  color: var(--bad);
}
.tone-start {
  background: var(--ok-soft);
  color: var(--ok);
}
.tone-alarm {
  background: var(--warn-soft);
  color: var(--warn);
}
.matrix td.tone-stop,
.matrix td.tone-start,
.matrix td.tone-alarm {
  font-weight: 600;
}
.matrix td.tone-stop {
  background: var(--bad-soft);
}
.matrix td.tone-start {
  background: var(--ok-soft);
}
.matrix td.tone-alarm {
  background: var(--warn-soft);
}
/* Several actions on one tag (pre-release PR 269): stacked chips, each in its own tone, on the cell's most severe tone. */
.cell.multi {
  padding: 4px 6px;
}
.cell .action {
  display: block;
  margin: 2px 0;
  border: 1px solid currentColor;
  line-height: 1.3;
}
/* Compared with another revision: what changed is outlined, a new interlock marked at its start. */
.matrix td.changed,
.changed {
  outline: 2px solid var(--modified);
  outline-offset: -2px;
}
.matrix tbody tr.added .c-id {
  box-shadow: inset 4px 0 0 var(--added);
}
.was {
  display: block;
  font-size: 11px;
  font-weight: normal;
  color: var(--fg-faint);
}
h2 {
  font-size: var(--text);
  margin: var(--space-4) 0 var(--space-2);
}
.notes dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--space-1) var(--space-3);
  margin: 0;
  font-size: var(--text-sm);
}
.notes dt {
  font-weight: 600;
}
.notes dd {
  margin: 0;
  color: var(--fg-muted);
}
.removed ul {
  padding-left: var(--space-4);
  font-size: var(--text-sm);
}

@media (max-width: 640px) {
  /* Narrow sticky columns leave room for the effects: the condition under the tag, no sheet. */
  .ce {
    --ce-id-w: 5.75rem;
  }
  .c-cause .condition {
    display: table;
    margin: 2px 0 0;
  }
  .c-cause .sheet {
    display: none;
  }
  .page.ce {
    padding: var(--space-3) var(--space-4);
  }
  .matrix th,
  .matrix td {
    padding: 4px 6px;
  }
  .legend {
    display: none;
  }
  .compare-select select {
    max-width: 180px;
  }
}
</style>
