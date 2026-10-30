<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { api } from "@/api";
import { store } from "@/store";
import LoadState from "@/components/LoadState.vue";
import MarkdownRender from "@/components/MarkdownRender";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { kindFromPath, paramPath, pathSegments, shortRev } from "@/lib/format";
import { lineWindow } from "@/lib/lineWindow";
import { highlightYaml, type YamlToken } from "@/lib/yamlHighlight";
import { fragmentOf, scrollToId } from "@/lib/inPageLink";
import { HEADING_ID_PREFIX } from "@/lib/markdown";
import { parseCsv } from "@/lib/studies";

const route = useRoute();
const { rev, withRev } = useRev();
const path = computed(() => paramPath(route.params.path));
const kind = computed(() => kindFromPath(path.value));
const file = useAsync((signal) => api.file(path.value, rev.value, signal), [path, rev]);
const raw = ref(false);
watch(path, () => (raw.value = false));

const text = computed(() => {
  const content = file.data.value ?? "";
  if (kind.value === "json" && !raw.value) {
    try {
      return JSON.stringify(JSON.parse(content), null, 2);
    } catch {
      return content;
    }
  }
  return content;
});
const lines = computed(() => text.value.split("\n"));
// A CSV (a generated schedule, inventory or estimate) reads as a table; its source is a click away.
const isCsv = computed(() => path.value.toLowerCase().endsWith(".csv"));
const csv = computed(() => {
  if (!isCsv.value || raw.value || file.data.value === null || targetLine.value) return null;
  const [header, ...body] = parseCsv(file.data.value);
  return header ? { header, body } : null;
});
const targetLine = computed(() => {
  const value = Number(Array.isArray(route.query.line) ? route.query.line[0] : route.query.line);
  return Number.isInteger(value) && value > 0 ? value : null;
});
const window_ = computed(() => lineWindow(lines.value.length, targetLine.value));
// YAML is highlighted as a whole (block scalars carry state across lines), then windowed.
const yamlTokens = computed<YamlToken[][] | null>(() =>
  kind.value === "yaml" && window_.value ? highlightYaml(text.value) : null,
);
const rows = computed(() => {
  const w = window_.value;
  if (!w) return [];
  const tokens = yamlTokens.value;
  return lines.value.slice(w.first - 1, w.last).map((text, i) => ({
    text,
    number: w.first + i,
    tokens: tokens?.[w.first - 1 + i] ?? null,
  }));
});
const source = ref<HTMLElement | null>(null);
watch(
  [() => file.data.value, targetLine, window_],
  async () => {
    if (!targetLine.value || file.data.value === null) return;
    await nextTick();
    source.value?.querySelector(`[data-line="${targetLine.value}"]`)?.scrollIntoView({ block: "center" });
  },
  { immediate: true },
);
// A link to a heading opened in a new tab (`README.md#design-basis`): scroll to it once rendered.
watch(
  [() => file.data.value, () => route.hash],
  async ([content, hash]) => {
    const id = fragmentOf(hash);
    if (content === null || !id || kind.value !== "markdown" || raw.value) return;
    await nextTick();
    scrollToId(HEADING_ID_PREFIX + id);
  },
  { immediate: true },
);
</script>

<template>
  <div class="page">
    <h1>{{ path }} <small>{{ shortRev(rev) }}</small></h1>
    <div class="toolbar">
      <RouterLink v-if="kind === 'pid'" class="btn" :to="{ name: 'pid', params: { path: pathSegments(path) }, query: withRev() }">Drawing</RouterLink>
      <RouterLink v-if="!store.snapshot" class="btn" :to="{ name: 'history', query: withRev({ path }) }">History</RouterLink>
      <span class="spacer" />
      <button v-if="kind === 'markdown' || kind === 'json' || isCsv" class="btn" type="button" @click="raw = !raw">
        {{ raw ? (kind === "markdown" ? "Rendered" : isCsv ? "Table" : "Formatted") : "Source" }}
      </button>
    </div>
    <LoadState :loading="file.loading.value && file.data.value === null" :error="file.error.value" @retry="file.reload" />
    <template v-if="file.data.value !== null">
      <article v-if="kind === 'markdown' && !raw" class="doc">
        <MarkdownRender :source="file.data.value" :path="path" :rev="rev" />
      </article>
      <template v-else-if="csv">
        <p class="muted window-note">{{ csv.body.length }} rows</p>
        <div class="table-wrap csv" data-testid="csv-table">
          <table class="data">
            <thead>
              <tr><th v-for="(h, i) in csv.header" :key="i">{{ h }}</th></tr>
            </thead>
            <tbody>
              <tr v-for="(row, r) in csv.body" :key="r">
                <td v-for="(cell, c) in row" :key="c" :class="{ num: cell.trim() !== '' && !Number.isNaN(Number(cell)) }">{{ cell }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
      <div v-else-if="!window_" class="source" role="region" aria-label="File content">
        <pre class="plain">{{ text }}</pre>
      </div>
      <template v-else>
        <p v-if="window_.partial" class="muted window-note">
          Lines {{ window_.first }}&ndash;{{ window_.last }} of {{ lines.length }}, around line {{ targetLine }}.
          <RouterLink :to="{ query: { ...route.query, line: undefined } }">Show the whole file</RouterLink>
        </p>
        <div ref="source" class="source" role="region" aria-label="File content">
          <table>
            <tbody>
              <tr v-for="row in rows" :key="row.number" :data-line="row.number" :class="{ target: targetLine === row.number }">
                <td class="ln">{{ row.number }}</td>
                <td class="code">
                  <pre v-if="row.tokens" class="yaml"><span v-for="(token, t) in row.tokens" :key="t" :class="`y-${token.type}`">{{ token.text }}</span></pre>
                  <pre v-else>{{ row.text }}</pre>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.doc {
  max-width: 860px;
  line-height: 1.6;
}
.doc :deep(h1),
.doc :deep(h2),
.doc :deep(h3) {
  line-height: 1.25;
  margin: 1.2em 0 0.5em;
}
.doc :deep(h1) {
  font-size: 1.6em;
}
.doc :deep(h2) {
  font-size: 1.3em;
  border-bottom: 1px solid var(--border);
  padding-bottom: 0.2em;
}
.doc :deep(h3) {
  font-size: 1.1em;
}
.doc :deep(code) {
  background: var(--bg-sunk);
  padding: 1px 4px;
  border-radius: 4px;
}
.doc :deep(pre.code) {
  background: var(--bg-soft);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--space-3);
  overflow: auto;
  white-space: pre;
}
.doc :deep(pre.code code) {
  background: none;
  padding: 0;
}
.doc :deep(blockquote) {
  margin: 0;
  padding: 0 var(--space-4);
  border-left: 3px solid var(--border);
  color: var(--fg-muted);
}
.doc :deep(.table-wrap) {
  margin: var(--space-3) 0;
}
.source {
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  font-size: var(--text-sm);
}
.source table {
  border-collapse: collapse;
  min-width: 100%;
}
.ln {
  user-select: none;
  text-align: right;
  color: var(--fg-faint);
  padding: 0 var(--space-2);
  border-right: 1px solid var(--border);
  background: var(--bg-soft);
  vertical-align: top;
  font-family: var(--mono);
  width: 1%;
}
.code {
  padding: 0 var(--space-3);
}
.csv {
  max-height: calc(100vh - 210px);
}
.csv td.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.window-note {
  margin: 0 0 var(--space-2);
  font-size: var(--text-sm);
}
.plain {
  padding: var(--space-3);
  white-space: pre;
  word-break: normal;
}
.yaml .y-key {
  color: var(--accent);
}
.yaml .y-punct {
  color: var(--fg-muted);
}
.yaml .y-comment {
  color: var(--fg-faint);
  font-style: italic;
}
.yaml .y-string {
  color: var(--ok);
}
.yaml .y-number,
.yaml .y-literal {
  color: var(--warn);
}
.yaml .y-anchor,
.yaml .y-tag,
.yaml .y-document {
  color: var(--bad);
}
tr.target td {
  background: var(--warn-soft);
}
.code pre {
  white-space: pre;
  word-break: normal;
  line-height: 1.5;
}
</style>
