<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { api, type FileKind, type TreeEntry } from "@/api";
import { store } from "@/store";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { KIND_ICON, KIND_LABEL, paramPath, pathSegments, viewFor } from "@/lib/format";
import { KIND_BADGE, groupSheets } from "@/lib/process";

interface Node {
  name: string;
  path: string;
  type: "file" | "dir";
  kind: FileKind;
  children: Node[];
}

const route = useRoute();
const { rev, withRev } = useRev();
const filter = ref("");
const expanded = reactive(new Set<string>());

const tree = useAsync((signal) => api.tree(rev.value, signal), rev);

const activePath = computed(() =>
  ["pid", "yaml", "file", "diff"].includes(String(route.name)) ? paramPath(route.params.path) : "",
);

// Open the folders above the file being shown.
watch(
  activePath,
  (path) => {
    const parts = pathSegments(path);
    for (let i = 1; i < parts.length; i++) expanded.add(parts.slice(0, i).join("/"));
  },
  { immediate: true },
);

function build(entries: TreeEntry[]): Node[] {
  const root: Node = { name: "", path: "", type: "dir", kind: "other", children: [] };
  const dirs = new Map<string, Node>([["", root]]);
  const ensureDir = (path: string): Node => {
    const existing = dirs.get(path);
    if (existing) return existing;
    const parts = path.split("/");
    const parent = ensureDir(parts.slice(0, -1).join("/"));
    const node: Node = { name: parts[parts.length - 1] ?? path, path, type: "dir", kind: "other", children: [] };
    parent.children.push(node);
    dirs.set(path, node);
    return node;
  };
  for (const entry of entries) {
    if (entry.type === "dir") {
      ensureDir(entry.path);
      continue;
    }
    const parts = entry.path.split("/");
    const parent = ensureDir(parts.slice(0, -1).join("/"));
    parent.children.push({ name: parts[parts.length - 1] ?? entry.path, path: entry.path, type: "file", kind: entry.kind, children: [] });
  }
  const sort = (node: Node) => {
    node.children.sort((a, b) => (a.type !== b.type ? (a.type === "dir" ? -1 : 1) : a.name.localeCompare(b.name)));
    node.children.forEach(sort);
  };
  sort(root);
  return root.children;
}

const nodes = computed(() => build(tree.data.value ?? []));

const kindOf = computed(() => new Map((tree.data.value ?? []).map((e) => [e.path, e.kind] as const)));

const sheets = computed(() =>
  (store.repo?.sheets ?? []).filter((s) => !tree.data.value || kindOf.value.has(s.file)),
);

const groups = computed(() => groupSheets(sheets.value));

const matches = computed(() => {
  const q = filter.value.trim().toLowerCase();
  if (!q) return null;
  return (tree.data.value ?? []).filter((e) => e.type === "file" && e.path.toLowerCase().includes(q));
});

/** Visible rows, depth-first, honouring collapsed folders. */
const rows = computed(() => {
  const out: { node: Node; depth: number }[] = [];
  const walk = (list: Node[], depth: number) => {
    for (const node of list) {
      out.push({ node, depth });
      if (node.type === "dir" && expanded.has(node.path)) walk(node.children, depth + 1);
    }
  };
  walk(nodes.value, 0);
  return out;
});

function toggle(path: string): void {
  if (expanded.has(path)) expanded.delete(path);
  else expanded.add(path);
}

function linkFor(path: string, kind: FileKind) {
  return { name: viewFor(kind), params: { path: pathSegments(path) }, query: withRev() };
}
</script>

<template>
  <div class="tree">
    <div class="filter">
      <label class="sr-only" for="tree-filter">Filter files</label>
      <input id="tree-filter" v-model="filter" type="search" placeholder="Filter files" autocomplete="off" />
    </div>

    <p v-if="tree.error.value" class="notice error small">{{ tree.error.value }}</p>

    <template v-if="matches">
      <ul class="list">
        <li v-for="entry in matches" :key="entry.path">
          <RouterLink class="row" :class="{ active: entry.path === activePath }" :to="linkFor(entry.path, entry.kind)" :title="entry.path">
            <span class="icon" :class="entry.kind" :title="KIND_LABEL[entry.kind]">{{ KIND_ICON[entry.kind] }}</span>
            <span class="label">{{ entry.path }}</span>
          </RouterLink>
        </li>
        <li v-if="!matches.length" class="empty">No matching files.</li>
      </ul>
    </template>

    <template v-else>
      <section v-for="group in groups" :key="group.id" :data-group="group.id">
        <h2>{{ group.title }}</h2>
        <ul class="list">
          <li v-for="sheet in group.sheets" :key="sheet.id">
            <RouterLink class="row" :class="{ active: sheet.file === activePath }" :to="linkFor(sheet.file, 'pid')" :title="sheet.file">
              <span class="icon pid">{{ KIND_ICON.pid }}</span>
              <span class="label"><strong>{{ sheet.id }}</strong> <span class="muted">{{ sheet.title }}</span></span>
              <span class="kind" :class="sheet.kind ?? 'pid'">{{ KIND_BADGE[sheet.kind ?? "pid"] }}</span>
            </RouterLink>
          </li>
          <li v-if="group.id === 'process'">
            <RouterLink class="row" :class="{ active: route.name === 'streams' }" :to="{ name: 'streams', query: withRev() }">
              <span class="icon">≡</span>
              <span class="label">Stream table</span>
            </RouterLink>
          </li>
        </ul>
      </section>

      <section>
        <h2>Files <span v-if="tree.loading.value" class="faint">loading&hellip;</span></h2>
        <ul class="list">
          <li v-for="{ node, depth } in rows" :key="node.path">
            <button
              v-if="node.type === 'dir'"
              type="button"
              class="row dir"
              :style="{ paddingLeft: `${8 + depth * 14}px` }"
              :aria-expanded="expanded.has(node.path)"
              @click="toggle(node.path)"
            >
              <span class="caret">{{ expanded.has(node.path) ? "▾" : "▸" }}</span>
              <span class="label">{{ node.name }}</span>
            </button>
            <RouterLink
              v-else
              class="row"
              :class="{ active: node.path === activePath }"
              :style="{ paddingLeft: `${8 + depth * 14}px` }"
              :to="linkFor(node.path, node.kind)"
              :title="node.path"
            >
              <span class="icon" :class="node.kind" :title="KIND_LABEL[node.kind]">{{ KIND_ICON[node.kind] }}</span>
              <span class="label">{{ node.name }}</span>
            </RouterLink>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.tree {
  padding: var(--space-2) 0 var(--space-6);
  font-size: var(--text-sm);
}
.filter {
  padding: 0 var(--space-3) var(--space-2);
}
.filter input {
  width: 100%;
}
h2 {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--fg-muted);
  margin: var(--space-3) var(--space-3) var(--space-1);
}
.list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.row {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 4px var(--space-3) 4px 8px;
  border: 0;
  background: none;
  color: var(--fg);
  text-align: left;
  cursor: pointer;
  border-left: 3px solid transparent;
  min-height: 28px;
}
.row:hover {
  background: var(--bg-sunk);
  text-decoration: none;
}
.row.active {
  background: var(--accent-soft);
  border-left-color: var(--accent);
}
.label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.caret {
  width: 14px;
  color: var(--fg-muted);
  flex: none;
}
.icon {
  width: 16px;
  flex: none;
  text-align: center;
  font-size: 11px;
  color: var(--fg-muted);
  font-family: var(--mono);
}
.icon.pid {
  color: var(--accent);
  font-size: 13px;
}
.icon.yaml {
  color: var(--ok);
}
.icon.markdown {
  color: var(--warn);
}
.icon.json {
  color: var(--bad);
}
.kind {
  margin-left: auto;
  flex: none;
  font-size: 10px;
  font-weight: 600;
  padding: 0 5px;
  border-radius: 3px;
  background: var(--bg-sunk);
  color: var(--fg-muted);
}
.kind.bfd,
.kind.pfd {
  background: var(--info-soft);
  color: var(--info);
}
.empty {
  padding: 4px var(--space-3);
  color: var(--fg-muted);
}
.small {
  margin: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
}
</style>
