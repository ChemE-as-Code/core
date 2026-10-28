<script setup lang="ts">
/**
 * The reaction library (`GET /api/library`, `cheme chemistry library`): industrial processes with
 * their components, reactions and typical catalysts, each item marked when the plant has it (a
 * component by its CAS number, a reaction by its stoichiometry, a catalyst by its id).
 */
import { computed, ref } from "vue";
import { api, ApiError, type LibraryView } from "@/api";
import LoadState from "@/components/LoadState.vue";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { shortRev } from "@/lib/format";
import { PROVENANCE_SHORT } from "@/lib/process";
import { rangeText } from "@/lib/reactions";
import { addCommand, filterLibrary, libraryMatch } from "@/lib/catalysis";

const { rev, withRev } = useRev();

/** The library at `rev`, or null from a server (or snapshot) without it (a 404). */
const report = useAsync<LibraryView | null>(async (signal) => {
  try {
    return await api.library(rev.value, signal);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}, rev);
const data = computed(() => report.data.value ?? null);
const missing = computed(() => !report.loading.value && !report.error.value && report.data.value === null);
const query = ref("");
const onlyPlant = ref(false);
const entries = computed(() => {
  const found = filterLibrary(data.value?.entries ?? [], query.value);
  return onlyPlant.value ? found.filter((e) => libraryMatch(e).runs) : found;
});
const inPlant = computed(() => (data.value?.entries ?? []).filter((e) => libraryMatch(e).runs).length);
const MATCH_BADGE = { all: "pass", some: "warning", none: "" } as const;
</script>

<template>
  <div class="page library-page">
    <h1>
      Reaction library
      <small>{{ rev ? `marked by the plant at ${shortRev(rev)}` : "marked by the plant's working tree" }}</small>
    </h1>

    <LoadState :loading="report.loading.value && !data" :error="report.error.value" @retry="report.reload" />
    <div v-if="missing" class="notice" data-library-missing>
      <p><strong>No reaction library here.</strong></p>
      <p class="muted">The page shows <code>cheme chemistry library</code>: this server or snapshot is older than it.</p>
    </div>

    <template v-if="data">
      <p class="muted small intro">
        Industrial processes with their components (ideal-gas data, critical constants), reactions and typical catalysts. <code>cheme chemistry library &lt;id&gt; --add</code> adds an entry to
        <code>process/materials.yaml</code>, <code>reactions.yaml</code> and <code>catalysts.yaml</code>; a mark says what the plant has already.
      </p>
      <div class="toolbar">
        <label class="field">
          Filter
          <input v-model="query" type="search" placeholder="process, component, catalyst" aria-label="Filter the library" data-library-filter />
        </label>
        <label class="field"><input v-model="onlyPlant" type="checkbox" data-library-only-plant /> Only processes the plant runs ({{ inPlant }})</label>
        <span class="spacer" />
        <RouterLink class="btn" :to="{ name: 'reactions', query: withRev() }">Reactions</RouterLink>
      </div>
      <p class="muted small">{{ entries.length }} of {{ data.entries.length }} entries</p>

      <div class="cards">
        <article v-for="e in entries" :key="e.id" class="card" :data-library-entry="e.id" :aria-label="e.title">
          <header>
            <strong>{{ e.title }}</strong>
            {{ " " }}<span class="mono muted small">{{ e.id }}</span>
            <span v-if="libraryMatch(e).state !== 'none'" class="badge" :class="MATCH_BADGE[libraryMatch(e).state]" :title="`The plant has ${libraryMatch(e).have} of its ${libraryMatch(e).of} components, reactions and catalysts`" data-match>
              {{ libraryMatch(e).state === "all" ? "in the plant" : `${libraryMatch(e).have} of ${libraryMatch(e).of} in the plant` }}
            </span>
          </header>
          <p class="small muted" data-window>{{ [rangeText(e.window.temperature, "K"), rangeText(e.window.pressure, "kPa(a)")].filter(Boolean).join(", ") }}</p>
          <div class="chips" aria-label="Components">
            <span v-for="c in e.components" :key="c.id" class="chip mono small" :class="{ have: c.in_plant }" :title="`${c.name}, CAS ${c.cas}${c.in_plant ? `: in the plant as ${c.in_plant}` : ''}`" :data-component="c.id">
              {{ c.id }}<template v-if="c.in_plant && c.in_plant !== c.id"> = {{ c.in_plant }}</template>
            </span>
          </div>
          <ul class="list small">
            <li v-for="r in e.reactions" :key="r.id" :data-library-reaction="r.id">
              <span class="mark" :class="{ have: r.in_plant }" :title="r.in_plant ? 'The plant has this reaction (same stoichiometry)' : 'Not in the plant'">{{ r.in_plant ? "✓" : "·" }}</span>
              <strong class="mono">{{ r.id }}</strong> <span class="mono">{{ r.equation }}</span>
              <span v-if="r.catalyst" class="muted"> on {{ r.catalyst }}</span>
            </li>
          </ul>
          <ul v-if="e.catalysts.length" class="list small">
            <li v-for="c in e.catalysts" :key="c.id" :data-library-catalyst="c.id">
              <span class="mark" :class="{ have: c.in_plant && !c.differs, differs: c.differs }" :title="c.differs ? 'The plant has a catalyst of this id with other data: --add refuses the entry until one is renamed' : c.in_plant ? 'The plant declares this catalyst' : 'Not in the plant'">{{ c.differs ? "≠" : c.in_plant ? "✓" : "·" }}</span>
              <strong class="mono">{{ c.id }}</strong> {{ c.name }}<span class="muted"> ({{ [c.active_phase, c.promoters.length ? `promoted ${c.promoters.join(", ")}` : "", c.support].filter(Boolean).join("; ") }})</span>
              <span v-if="c.window" class="prov" :class="c.window.provenance" :title="[c.window.provenance, c.window.source].filter(Boolean).join(': ')">{{ PROVENANCE_SHORT[c.window.provenance] }}</span>
              <div v-if="c.poisons.length" class="muted">poisons: {{ c.poisons.join(", ") }}</div>
            </li>
          </ul>
          <details v-if="e.sources.length" class="sources">
            <summary>{{ e.sources.length }} source{{ e.sources.length === 1 ? "" : "s" }}</summary>
            <ul>
              <li v-for="(src, i) in e.sources" :key="i">{{ src }}</li>
            </ul>
          </details>
          <p class="mono small muted add" data-add>{{ addCommand(e.id) }}</p>
        </article>
      </div>
      <p v-if="!entries.length" class="muted" data-library-empty>No entry matches.</p>
    </template>
  </div>
</template>

<style scoped>
.intro {
  max-width: 80ch;
}
.field {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-sm);
}
.small {
  font-size: var(--text-sm);
}
.mono {
  font-family: var(--mono);
  font-size: 12px;
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 380px), 1fr));
  gap: var(--space-3, 12px);
}
.card {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  padding: var(--space-3, 12px);
  min-width: 0;
  overflow-wrap: anywhere;
}
.card header {
  margin-bottom: var(--space-1, 4px);
}
.card header .badge {
  margin-left: 6px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin: var(--space-2, 8px) 0;
}
.chip {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 0 6px;
}
.chip.have {
  border-color: var(--ok);
  background: var(--ok-soft);
}
.list {
  list-style: none;
  margin: var(--space-2, 8px) 0;
  padding: 0;
}
.list li {
  margin: 2px 0;
}
.mark {
  display: inline-block;
  width: 1.2em;
  color: var(--fg-muted);
}
.mark.differs {
  color: var(--warn);
  font-weight: 600;
}
.mark.have {
  color: var(--ok);
  font-weight: 600;
}
.sources summary {
  font-size: 11.5px;
}
.sources ul {
  margin: 0;
  padding-left: var(--space-4);
  font-size: 11.5px;
}
.add {
  margin: var(--space-2, 8px) 0 0;
}
</style>
