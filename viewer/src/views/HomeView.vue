<script setup lang="ts">
import { computed, watch } from "vue";
import { loadMaturity, maturity, store } from "@/store";
import { useRev } from "@/lib/useRev";
import { pathSegments } from "@/lib/format";
import { KIND_BADGE, groupSheets } from "@/lib/process";
import SignoffStrip from "@/components/SignoffStrip.vue";
import { PHASE_NOTE, maturityBadge } from "@/lib/maturity";
import { useNavGroups } from "@/lib/useNavGroups";

const { rev, withRev } = useRev();
// once per revision, shared with the header (which an embedding page hides)
watch([rev, () => store.repo], ([value, loaded]) => loaded && void loadMaturity(value), { immediate: true });
const nav = useNavGroups();
const maturityState = computed(() => maturityBadge(maturity[rev.value ?? ""] ?? { kind: "loading" }));
const repo = computed(() => store.repo);
const groups = computed(() => groupSheets(repo.value?.sheets ?? []));
// The pages and documents (the sheets have their cards above).
const pages = computed(() =>
  nav.value.map((g) => ({ ...g, items: g.items.filter((i) => i.to.name !== "pid") })).filter((g) => g.items.length),
);
</script>

<template>
  <div class="page">
    <template v-if="repo">
      <h1>{{ repo.name || repo.root_name }} <small>{{ repo.root_name }}</small></h1>
      <dl class="facts">
        <dt>Branch</dt>
        <dd>
          <code>{{ repo.branch ?? "(detached)" }}</code>
          <span v-if="repo.head" class="faint"> at <code>{{ repo.head.slice(0, 8) }}</code></span>
          <span v-if="repo.dirty" class="badge dirty">uncommitted changes</span>
          <span v-else class="badge clean">clean</span>
        </dd>
        <dt><abbr :title="PHASE_NOTE">Project phase</abbr></dt>
        <dd>
          <ol class="stages">
            <li v-for="s in repo.stages" :key="s.id" :class="{ current: s.id === repo.stage }">
              {{ s.title }}
            </li>
          </ol>
        </dd>
        <dt>Verified maturity</dt>
        <dd>
          <RouterLink class="badge" :class="maturityState.tone" :to="{ name: 'maturity', query: withRev() }" :title="maturityState.title" data-testid="home-maturity">{{ maturityState.value }}</RouterLink>
          <span class="muted maturity-note">evidence-based calculation maturity, independent of the declared phase</span>
        </dd>
        <dt>Sign-off</dt>
        <dd class="signoff-dd">
          <SignoffStrip />
          <RouterLink class="reviews-link" :to="{ name: 'reviews', query: withRev() }">Review findings</RouterLink>
        </dd>
      </dl>

      <template v-for="group in groups" :key="group.id">
        <h2 class="sheet-group">
          <RouterLink class="section-link" :to="{ name: 'section', params: { id: group.id }, query: withRev() }">{{
            group.id === "pid" ? "P&ID sheets" : group.title
          }}</RouterLink>
        </h2>
        <div class="cards">
          <template v-for="s in group.sheets" :key="s.id">
            <!-- A planned sheet is listed in plant.yaml but not drawn yet: there is nothing to open. -->
            <div v-if="s.status === 'planned'" class="card planned" :data-sheet="s.id">
              <strong>{{ s.id }} <span class="badge">planned</span></strong>
              <span>{{ s.title }}</span>
              <code class="faint">{{ s.file }}</code>
            </div>
            <RouterLink v-else class="card" :data-sheet="s.id" :to="{ name: 'pid', params: { path: pathSegments(s.file) }, query: withRev() }">
              <strong>{{ s.id }} <span v-if="s.kind && s.kind !== 'pid'" class="badge stage">{{ KIND_BADGE[s.kind] }}</span></strong>
              <span>{{ s.title }}</span>
              <code class="faint">{{ s.file }}</code>
            </RouterLink>
          </template>
          <RouterLink v-if="group.id === 'process'" class="card" :to="{ name: 'streams', query: withRev() }">
            <strong>Stream table</strong>
            <span>Values, provenance and balances</span>
            <code class="faint">process/flowsheet.yaml</code>
          </RouterLink>
        </div>
      </template>
      <p v-if="!repo.sheets.length" class="muted">No sheets in plant.yaml.</p>

      <h2>Pages and documents</h2>
      <div class="page-groups" data-testid="home-pages">
        <section v-for="g in pages" :key="g.id" :data-group="g.id">
          <h3><RouterLink class="section-link" :to="{ name: 'section', params: { id: g.id }, query: withRev() }">{{ g.title }}</RouterLink></h3>
          <ul>
            <li v-for="item in g.items" :key="item.key">
              <RouterLink :to="{ ...item.to, query: withRev(item.to.query) }" :title="item.title">{{ item.label }}</RouterLink>
            </li>
          </ul>
        </section>
      </div>
    </template>
    <p v-else-if="store.loading" class="muted">Loading&hellip;</p>
  </div>
</template>

<style scoped>
.facts {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--space-2) var(--space-4);
  margin: 0 0 var(--space-4);
}
.facts dt {
  color: var(--fg-muted);
}
.facts dd {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: center;
}
.facts dd.signoff-dd {
  display: block;
  min-width: 0;
}
.maturity-note {
  font-size: var(--text-sm);
}
.reviews-link {
  display: inline-block;
  margin-top: var(--space-1);
  font-size: var(--text-sm);
}
.stages {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  list-style: none;
  margin: 0;
  padding: 0;
  counter-reset: stage;
}
.stages li {
  counter-increment: stage;
  padding: 2px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: var(--text-sm);
  color: var(--fg-muted);
}
.stages li::before {
  content: counter(stage) ". ";
}
.stages li.current {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--fg);
  font-weight: 600;
}
h2 {
  font-size: var(--text);
  margin: var(--space-4) 0 var(--space-2);
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--space-3);
}
.card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--fg);
}
.card:hover {
  border-color: var(--accent);
  text-decoration: none;
}
.card.planned {
  border-style: dashed;
  color: var(--fg-muted);
}
.card.planned:hover {
  border-color: var(--border);
}
.page-groups {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--space-3) var(--space-4);
}
.page-groups h3 {
  font-size: var(--text-sm);
  color: var(--fg-muted);
  margin: 0 0 var(--space-1);
}
/* a heading that opens its section page (`/section/<id>`): the heading's colour, a chevron as the cue */
.section-link {
  color: inherit;
}
.section-link::after {
  content: "\203A" / ""; /* decorative: not part of the link's name */
  margin-left: 0.35em;
  color: var(--fg-muted);
}
.section-link:hover,
.section-link:hover::after {
  color: var(--accent);
  text-decoration: none;
}
.page-groups ul {
  list-style: none;
  margin: 0;
  padding: 0;
}
.page-groups li {
  padding: 2px 0;
}
</style>
