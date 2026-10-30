<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute } from "vue-router";
import { api } from "@/api";
import JsonTree from "@/components/JsonTree.vue";
import YamlDocument from "@/components/YamlDocument.vue";
import LoadState from "@/components/LoadState.vue";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { cellText, processSections, yamlTable } from "@/lib/yamlTable";
import { documentBlocks } from "@/lib/yamlDocument";
import { isRecord } from "@/lib/guards";
import { paramPath, pathSegments, shortRev } from "@/lib/format";

const route = useRoute();
const { rev, withRev } = useRev();
const path = computed(() => paramPath(route.params.path));
const doc = useAsync((signal) => api.yaml(path.value, rev.value, signal), [path, rev]);

// The process files (materials, flowsheet) hold several lists: one table per section.
const sections = computed(() => (doc.data.value ? processSections(doc.data.value) : null));
const section = ref<string | null>(null);
const table = computed(() => {
  const all = sections.value;
  if (all) return all.find((t) => t.key === section.value) ?? all[0] ?? null;
  return doc.data.value ? yamlTable(doc.data.value) : null;
});
// Not a table (the design basis, a study): a readable document, the tree one click away.
const blocks = computed(() => {
  const data = doc.data.value?.data;
  return !table.value && isRecord(data) ? documentBlocks(data) : null;
});
const showEmpty = ref(false);
// `?filter=`: the filter the page opens with (a datasheet's nozzle links its line in the line list).
const filter = ref(typeof route.query.filter === "string" ? route.query.filter : "");
const sortKey = ref<string | null>(null);
const sortDir = ref<1 | -1>(1);
const asTree = ref(false);

/** Columns that have a value in at least one row (all of them when showEmpty). */
const columns = computed(() => {
  const t = table.value;
  if (!t) return [];
  if (showEmpty.value) return t.columns;
  return t.columns.filter((c) => c.required || t.rows.some((r) => cellText(r[c.key]) !== ""));
});
const hiddenCount = computed(() => (table.value?.columns.length ?? 0) - columns.value.length);

const rows = computed(() => {
  const t = table.value;
  if (!t) return [];
  const q = filter.value.trim().toLowerCase();
  let list = t.rows.map((row, index) => ({ row, index }));
  if (q) list = list.filter(({ row }) => Object.values(row).some((v) => cellText(v).toLowerCase().includes(q)));
  const key = sortKey.value;
  if (key) {
    list = [...list].sort((a, b) => {
      const x = a.row[key];
      const y = b.row[key];
      if (typeof x === "number" && typeof y === "number") return (x - y) * sortDir.value;
      return cellText(x).localeCompare(cellText(y), undefined, { numeric: true }) * sortDir.value;
    });
  }
  return list;
});

function sortBy(key: string): void {
  if (sortKey.value === key) sortDir.value = sortDir.value === 1 ? -1 : 1;
  else {
    sortKey.value = key;
    sortDir.value = 1;
  }
}
</script>

<template>
  <div class="page">
    <h1>
      {{ path }}
      <small>{{ shortRev(rev) }}</small>
      <span v-if="doc.data.value?.kind" class="badge info">{{ doc.data.value.kind }}</span>
    </h1>
    <div class="toolbar">
      <template v-if="table && !asTree">
        <div v-if="sections" class="sections" role="tablist" aria-label="Section">
          <button
            v-for="t in sections"
            :key="t.key ?? ''"
            type="button"
            role="tab"
            class="btn"
            :class="{ active: t.key === table.key }"
            :aria-selected="t.key === table.key"
            @click="section = t.key; sortKey = null"
          >
            {{ t.key }} <span class="faint">{{ t.rows.length }}</span>
          </button>
        </div>
        <RouterLink v-if="doc.data.value?.kind === 'flowsheet'" class="btn" :to="{ name: 'streams', query: withRev() }">Stream table</RouterLink>
        <input v-model="filter" type="search" placeholder="Filter rows" aria-label="Filter rows" />
        <label class="check"><input v-model="showEmpty" type="checkbox" /> empty columns<span v-if="hiddenCount" class="faint"> ({{ hiddenCount }} hidden)</span></label>
      </template>
      <span class="spacer" />
      <button v-if="table || blocks" class="btn" type="button" @click="asTree = !asTree">{{ asTree ? (table ? "Table" : "Document") : "Tree" }}</button>
      <RouterLink class="btn" :to="{ name: 'file', params: { path: pathSegments(path) }, query: withRev() }">Source</RouterLink>
    </div>

    <LoadState :loading="doc.loading.value && !doc.data.value" :error="doc.error.value" @retry="doc.reload" />

    <template v-if="doc.data.value">
      <template v-if="table && !asTree">
        <p class="muted count">
          {{ rows.length }} of {{ table.rows.length }} {{ table.key ?? "rows" }}
        </p>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr>
                <th v-for="c in columns" :key="c.key" :title="[c.description, c.type].filter(Boolean).join(' — ')" :aria-sort="sortKey === c.key ? (sortDir === 1 ? 'ascending' : 'descending') : 'none'">
                  <button type="button" class="sort" @click="sortBy(c.key)">
                    {{ c.title }}<span v-if="c.required" class="req" title="required">*</span>
                    <span v-if="c.extra" class="faint" title="Not in the schema"> ?</span>
                    <span class="arrow">{{ sortKey === c.key ? (sortDir === 1 ? "▲" : "▼") : "" }}</span>
                  </button>
                  <div v-if="c.type" class="type">{{ c.type }}</div>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="{ row, index } in rows" :key="index">
                <td v-for="c in columns" :key="c.key" :class="{ num: typeof row[c.key] === 'number' }">{{ cellText(row[c.key]) }}</td>
              </tr>
              <tr v-if="!rows.length">
                <td :colspan="columns.length || 1" class="muted">No rows.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
      <YamlDocument v-else-if="blocks && !asTree" :blocks="blocks" data-testid="yaml-document" />
      <div v-else class="tree">
        <JsonTree :value="doc.data.value.data" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.check {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-sm);
}
.sections {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 2px;
}
.count {
  margin: 0 0 var(--space-2);
  font-size: var(--text-sm);
}
.table-wrap {
  max-height: calc(100vh - 210px);
}
.sort {
  border: 0;
  background: none;
  padding: 0;
  font-weight: 600;
  cursor: pointer;
}
.req {
  color: var(--bad);
  margin-left: 1px;
}
.arrow {
  font-size: 9px;
  margin-left: 3px;
}
.type {
  font-weight: normal;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--fg-faint);
}
td.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.tree {
  padding: var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  overflow: auto;
}
</style>
