<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, type Change, type ChangeKind } from "@/api";
import SvgPane, { type Layer, type Picked } from "@/components/SvgPane.vue";
import InfoPanel from "@/components/InfoPanel.vue";
import LoadState from "@/components/LoadState.vue";
import { sanitizeSvg, type SanitizedSvg } from "@/lib/sanitize";
import { createView } from "@/lib/panzoom";
import { highlightCss, selectionCss } from "@/lib/highlight";
import { changesForDrawn, drawnId, drawnIdOn, emptyChangesText, plantItem } from "@/lib/diffOwners";
import { useAsync } from "@/lib/useAsync";
import { paramPath, pathSegments, shortRev } from "@/lib/format";
import { store } from "@/store";

const route = useRoute();
const router = useRouter();
const path = computed(() => paramPath(route.params.path));
const queryValue = (key: string): string | undefined => {
  const value = route.query[key];
  const first = Array.isArray(value) ? value[0] : value;
  return first ? String(first) : undefined;
};
const oldRev = computed(() => queryValue("old") ?? "HEAD");
const newRev = computed(() => queryValue("new"));

const OLD = "diff-old";
const NEW = "diff-new";

interface Loaded {
  diff: Awaited<ReturnType<typeof api.diff>>;
  oldSvg: SanitizedSvg | null;
  newSvg: SanitizedSvg | null;
}

const result = useAsync<Loaded>(async (signal) => {
  const diff = await api.diff(path.value, oldRev.value, newRev.value, signal);
  return {
    diff,
    oldSvg: diff.old_svg ? sanitizeSvg(diff.old_svg) : null,
    newSvg: diff.new_svg ? sanitizeSvg(diff.new_svg) : null,
  };
}, [path, oldRev, newRev]);

const mode = ref<"side" | "overlay">(window.matchMedia?.("(max-width: 700px)").matches ? "overlay" : "side");
const overlayOpacity = ref(0.6);
const view = createView();
const picked = ref<Picked | null>(null);
const selectedId = ref<string | null>(null);
const kindFilter = ref<ChangeKind | "all">("all");
const oldPane = ref<InstanceType<typeof SvgPane> | null>(null);
const newPane = ref<InstanceType<typeof SvgPane> | null>(null);

const diff = computed(() => result.data.value?.diff ?? null);
const changes = computed<Change[]>(() => {
  const list = [...(diff.value?.changes ?? [])];
  list.sort((a, b) => Number(a.domain !== "conceptual") - Number(b.domain !== "conceptual") || a.kind.localeCompare(b.kind));
  return list;
});
const shownChanges = computed(() =>
  kindFilter.value === "all" ? changes.value : changes.value.filter((c) => c.kind === kindFilter.value),
);
const counts = computed(() => {
  const out: Record<ChangeKind, number> = { added: 0, removed: 0, modified: 0, moved: 0 };
  for (const c of changes.value) if (c.kind in out) out[c.kind] += 1;
  return out;
});

const css = computed(() => {
  const d = diff.value;
  if (!d) return "";
  const id = selectedId.value;
  return [
    highlightCss(OLD, d.old_highlight),
    highlightCss(NEW, d.new_highlight),
    selectionCss(OLD, id),
    selectionCss(NEW, id),
  ].join("\n");
});

const oldLayers = computed<Layer[]>(() => [{ id: OLD, svg: result.data.value?.oldSvg ?? null }]);
const newLayers = computed<Layer[]>(() => [{ id: NEW, svg: result.data.value?.newSvg ?? null }]);
const overlayLayers = computed<Layer[]>(() => [
  { id: OLD, svg: result.data.value?.oldSvg ?? null },
  { id: NEW, svg: result.data.value?.newSvg ?? null, opacity: overlayOpacity.value },
]);

const oldLabel = computed(() => diff.value?.old_rev || oldRev.value);
const newLabel = computed(() => diff.value?.new_rev || shortRev(newRev.value));

/** Changes that touch the picked object, by its id or the id it is drawn for. */
const pickedChanges = computed(() => {
  const id = picked.value?.id;
  if (!id || !diff.value) return [];
  return changesForDrawn(diff.value, changes.value, id);
});
const ownerOf = (change: Change): string | null => (diff.value ? drawnId(diff.value, change) : null);
const itemOf = (change: Change) => (diff.value ? plantItem(diff.value, change) : null);
const emptyText = computed(() => (diff.value ? emptyChangesText(diff.value) : ""));

watch(
  () => result.data.value,
  async (data) => {
    if (!data) return;
    await nextTick();
    (newPane.value ?? oldPane.value)?.fit();
  },
);

function onPick(value: Picked | null): void {
  picked.value = value;
  selectedId.value = value?.id ?? null;
}
// The picked object (its labels and changes) belongs to the diff it was picked in.
watch([path, oldRev, newRev], () => onPick(null));

async function selectChange(change: Change): Promise<void> {
  const d = diff.value;
  // A nozzle, pipe or node is shown by the drawing around it (the server's owner maps).
  selectedId.value = (d && drawnId(d, change)) ?? change.object_id;
  await nextTick();
  const panes: [InstanceType<typeof SvgPane> | null, string | null][] =
    mode.value === "overlay"
      ? [[newPane.value, (d && (drawnIdOn(d, change, "new") ?? drawnIdOn(d, change, "old"))) ?? change.object_id]]
      : [
          [newPane.value, (d && drawnIdOn(d, change, "new")) ?? change.object_id],
          [oldPane.value, (d && drawnIdOn(d, change, "old")) ?? change.object_id],
        ];
  for (const [pane, id] of panes) if (id && pane?.focus(id)) break;
}

// Revision form.
const oldInput = ref(oldRev.value);
const newInput = ref(newRev.value ?? "");
watch([oldRev, newRev], ([o, n]) => {
  oldInput.value = o;
  newInput.value = n ?? "";
});
const revOptions = computed(() => ["HEAD", ...store.branches.map((b) => b.name)]);

function compare(): void {
  const old = oldInput.value.trim() || "HEAD";
  const next = newInput.value.trim();
  if (old.startsWith("-") || next.startsWith("-")) return;
  const query: Record<string, string> = { old };
  if (next) query.new = next;
  void router.replace({ query });
}

function swap(): void {
  if (!newRev.value) return;
  void router.replace({ query: { old: newRev.value, new: oldRev.value } });
}

const projectionLines = computed(() =>
  (diff.value?.projection_diff ?? "").split("\n").map((text) => ({
    text,
    cls: text.startsWith("+++") || text.startsWith("---") ? "meta" : text.startsWith("+") ? "add" : text.startsWith("-") ? "del" : text.startsWith("@@") ? "hunk" : "",
  })),
);
</script>

<template>
  <div class="diff">
    <div class="bar">
      <h1>
        <RouterLink :to="{ name: 'pid', params: { path: pathSegments(path) } }">{{ path }}</RouterLink>
        <small>{{ oldLabel }} &rarr; {{ newLabel }}</small>
      </h1>
      <form class="revs" @submit.prevent="compare">
        <label>
          <span class="sr-only">Old revision</span>
          <input v-model="oldInput" type="text" list="diff-revs" placeholder="old (HEAD)" spellcheck="false" />
        </label>
        <span aria-hidden="true">&rarr;</span>
        <label>
          <span class="sr-only">New revision</span>
          <input v-model="newInput" type="text" list="diff-revs" placeholder="working tree" spellcheck="false" />
        </label>
        <datalist id="diff-revs">
          <option v-for="r in revOptions" :key="r" :value="r" />
        </datalist>
        <button class="btn" type="submit">Compare</button>
        <button class="btn" type="button" :disabled="!newRev" title="Swap old and new" @click="swap">&#8646;</button>
      </form>
      <div class="modes" role="group" aria-label="Layout">
        <button class="btn" type="button" :class="{ active: mode === 'side' }" :aria-pressed="mode === 'side'" @click="mode = 'side'">
          Side by side
        </button>
        <button class="btn" type="button" :class="{ active: mode === 'overlay' }" :aria-pressed="mode === 'overlay'" @click="mode = 'overlay'">
          Overlay
        </button>
        <label v-if="mode === 'overlay'" class="opacity">
          <span class="muted">new</span>
          <input v-model.number="overlayOpacity" type="range" min="0" max="1" step="0.05" aria-label="Opacity of the new revision" />
        </label>
      </div>
    </div>

    <LoadState class="state" :loading="result.loading.value && !diff" :error="result.error.value" @retry="result.reload" />

    <div class="canvas" :class="mode">
      <template v-if="mode === 'side'">
        <SvgPane ref="oldPane" :layers="oldLayers" :view="view" :css="css" :auto-fit="false" :label="oldLabel" empty-text="(not present)" @pick="onPick" />
        <SvgPane ref="newPane" :layers="newLayers" :view="view" :css="css" :auto-fit="false" :label="newLabel" empty-text="(not present)" @pick="onPick" />
      </template>
      <SvgPane
        v-else
        ref="newPane"
        :layers="overlayLayers"
        :view="view"
        :css="css"
        :auto-fit="false"
        :label="`${oldLabel} under ${newLabel}`"
        empty-text="(not present)"
        @pick="onPick"
      />
      <InfoPanel :picked="picked" :changes="pickedChanges" @close="onPick(null)" />
    </div>

    <section v-if="diff" class="details">
      <div class="summary">
        <button class="btn" type="button" :class="{ active: kindFilter === 'all' }" @click="kindFilter = 'all'">
          All {{ changes.length }}
        </button>
        <button
          v-for="kind in ['added', 'removed', 'modified', 'moved'] as const"
          :key="kind"
          class="btn"
          type="button"
          :class="{ active: kindFilter === kind }"
          :disabled="!counts[kind]"
          @click="kindFilter = kind"
        >
          <span class="dot" :class="kind" aria-hidden="true" />{{ counts[kind] }} {{ kind }}
        </button>
      </div>

      <p v-if="diff.status && shownChanges.length" class="notice">{{ emptyText }}</p>
      <div v-if="shownChanges.length" class="table-wrap changes">
        <table class="data">
          <thead>
            <tr><th>change</th><th>domain</th><th>class</th><th>tag</th><th>id</th><th>attributes</th></tr>
          </thead>
          <tbody>
            <tr
              v-for="(c, i) in shownChanges"
              :key="`${c.object_id}-${c.kind}-${i}`"
              class="clickable"
              :class="{ selected: (ownerOf(c) ?? c.object_id) === selectedId, undrawn: !ownerOf(c) }"
              :title="ownerOf(c) ? `Drawn as ${ownerOf(c)}` : 'Not drawn on the sheet'"
              tabindex="0"
              @click="selectChange(c)"
              @keydown.enter="selectChange(c)"
            >
              <td><span class="badge" :class="c.kind">{{ c.kind }}</span></td>
              <td>{{ c.domain }}</td>
              <td>{{ c.object_type }}</td>
              <td>{{ c.tag ?? "" }}</td>
              <td>
                <code>{{ c.object_id }}</code>
                <span v-if="!ownerOf(c)" class="muted not-drawn">not drawn</span>
                <span v-else-if="ownerOf(c) !== c.object_id" class="muted not-drawn">in {{ ownerOf(c) }}</span>
                <span v-if="itemOf(c)" class="muted item">
                  of {{ [itemOf(c)!.class, itemOf(c)!.tag || itemOf(c)!.id].filter(Boolean).join(" ") }}
                </span>
              </td>
              <td class="detail">{{ c.detail }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="muted">{{ emptyText }}</p>

      <details class="projection">
        <summary>Review text (pyDEXPI projection)</summary>
        <pre v-if="diff.projection_diff"><span v-for="(line, i) in projectionLines" :key="i" :class="line.cls">{{ line.text }}
</span></pre>
        <p v-else class="muted">(no difference)</p>
      </details>
    </section>
  </div>
</template>

<style scoped>
.diff {
  display: flex;
  flex-direction: column;
  min-height: 100%;
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
  flex-wrap: wrap;
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
.revs,
.modes {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1);
}
.revs input {
  width: 130px;
}
.modes {
  margin-left: auto;
}
.opacity {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-sm);
}
.state {
  margin: var(--space-2) var(--space-4);
}
.canvas {
  position: relative;
  display: grid;
  gap: 2px;
  height: max(360px, 62vh);
  background: var(--border);
}
.canvas.side {
  grid-template-columns: 1fr 1fr;
}
.canvas.overlay {
  grid-template-columns: 1fr;
}
.not-drawn,
.item {
  font-size: var(--text-sm);
  margin-left: var(--space-1);
}
tr.undrawn {
  cursor: default;
}
.details {
  padding: var(--space-3) var(--space-4) var(--space-6);
}
.summary {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  margin-bottom: var(--space-3);
}
.dot {
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  margin-right: 4px;
  background: var(--fg-faint);
}
.dot.added {
  background: var(--added);
}
.dot.removed {
  background: var(--removed);
}
.dot.modified,
.dot.moved {
  background: var(--modified);
}
.changes {
  max-height: 46vh;
}
.detail {
  word-break: break-word;
  min-width: 220px;
}
.projection {
  margin-top: var(--space-3);
}
.projection pre {
  background: var(--bg-soft);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--space-3);
  max-height: 60vh;
  overflow: auto;
  font-size: var(--text-sm);
}
.projection .add {
  color: var(--ok);
}
.projection .del {
  color: var(--bad);
}
.projection .hunk {
  color: var(--info);
}
.projection .meta {
  color: var(--fg-muted);
}

@media (max-width: 700px) {
  .canvas.side {
    grid-template-columns: 1fr;
    grid-template-rows: 1fr 1fr;
    height: 80vh;
  }
  .modes {
    margin-left: 0;
  }
  .revs input {
    width: 110px;
  }
}
</style>
