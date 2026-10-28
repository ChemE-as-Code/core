<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { loadMaturity, maturity, store } from "@/store";
import { useRev } from "@/lib/useRev";
import { shortRev } from "@/lib/format";
import { hasReviewData } from "@/lib/reviews";
import { PHASE_NOTE, maturityBadge } from "@/lib/maturity";

defineProps<{ sidebarOpen: boolean }>();
defineEmits<{ toggleSidebar: [] }>();

const route = useRoute();
const router = useRouter();
const { rev, withRev } = useRev();
const customRev = ref("");
const logo = `${import.meta.env.BASE_URL}logo.svg`;

const stageTitle = computed(() => {
  const repo = store.repo;
  if (!repo?.stage) return null;
  return repo.stages.find((s) => s.id === repo.stage)?.title ?? repo.stage;
});

// The evidence-based maturity of the revision shown (never another revision's), once loaded.
watch(
  [rev, () => store.repo],
  ([value, repo]) => {
    if (repo) void loadMaturity(value);
  },
  { immediate: true },
);
const badge = computed(() => maturityBadge(maturity[rev.value ?? ""] ?? { kind: "loading" }));

/** Options: working tree, every branch, and the current rev when it is not a branch. */
const options = computed(() => {
  const list = [{ value: "", label: store.repo?.dirty ? "working tree (uncommitted changes)" : "working tree" }];
  for (const branch of store.branches)
    list.push({ value: branch.name, label: `${branch.name}${branch.current ? " (checked out)" : ""}` });
  if (rev.value && !store.branches.some((b) => b.name === rev.value))
    list.push({ value: rev.value, label: shortRev(rev.value) });
  return list;
});

function setRev(value: string): void {
  const query = { ...route.query };
  if (value) query.rev = value;
  else delete query.rev;
  void router.replace({ query });
}

function onSelect(event: Event): void {
  setRev((event.target as HTMLSelectElement).value);
}

const showCustom = ref(false);
function openCustom(): void {
  customRev.value = rev.value ?? "";
  showCustom.value = true;
}
function applyCustom(): void {
  const value = customRev.value.trim();
  showCustom.value = false;
  if (value && !value.startsWith("-")) setRev(value);
}
</script>

<template>
  <header class="header">
    <button
      class="btn menu"
      type="button"
      :aria-expanded="sidebarOpen"
      aria-label="Toggle file list"
      @click="$emit('toggleSidebar')"
    >
      &#9776;
    </button>
    <RouterLink class="brand" :to="{ name: 'home', query: withRev() }">
      <img class="logo" :src="logo" alt="" width="34" height="34" data-testid="header-logo" />
      <span class="name">{{ store.repo?.name || store.repo?.root_name || "cheme-as-code" }}</span>
    </RouterLink>
    <span
      v-if="stageTitle"
      class="badge stage"
      :title="`${PHASE_NOTE} (plant.yaml stage: ${store.repo?.stage})`"
      data-testid="phase-badge"
      ><span class="badge-key">Project phase:</span> {{ stageTitle }}</span
    >
    <RouterLink
      v-if="store.repo"
      class="badge maturity"
      :class="badge.tone"
      :to="{ name: 'maturity', query: withRev() }"
      :title="badge.title"
      data-testid="maturity-badge"
      ><span class="badge-key">Verified maturity:</span> {{ badge.value }}</RouterLink
    >

    <nav class="nav" aria-label="Pages">
      <RouterLink :to="{ name: 'checks', query: withRev() }">Checks</RouterLink>
      <RouterLink :to="{ name: 'validate', query: withRev() }">Validation</RouterLink>
      <RouterLink :to="{ name: 'maturity', query: withRev() }" title="Evidence-based calculation maturity (cheme maturity): the four levels and their requirements">Maturity</RouterLink>
      <RouterLink v-if="hasReviewData(store.status)" :to="{ name: 'reviews', query: withRev() }" title="Open review findings and stage sign-offs">Reviews</RouterLink>
      <RouterLink v-if="store.hasInterlocks" :to="{ name: 'cause-effect', query: withRev() }" title="Cause and effect matrix of the interlocks (control/cause-effect.yaml)">C&amp;E</RouterLink>
      <RouterLink v-if="store.hasHazop" :to="{ name: 'hazop', query: withRev() }" title="HAZOP studies as worksheets (safety/hazop/)">HAZOP</RouterLink>
      <RouterLink v-if="store.repo?.has_control" :to="{ name: 'control', query: withRev() }" title="Control loops, sequences, narrative and control philosophy (cheme control report)">Control</RouterLink>
      <RouterLink v-if="store.repo?.has_issues" :to="{ name: 'issues', query: withRev() }" title="Action items, engineering holds, technical queries and design changes (GitHub issues, cheme issues)">Issues</RouterLink>
      <RouterLink v-if="store.repo?.has_reactions" :to="{ name: 'reactions', query: withRev() }" title="Reactions and reactors (process/reactions.yaml)">Reactions</RouterLink>
      <RouterLink v-if="store.hasDatasheets" :to="{ name: 'datasheets', query: withRev() }" title="Equipment datasheets (equipment/datasheets/)">Datasheets</RouterLink>
      <RouterLink v-if="!store.snapshot" :to="{ name: 'history', query: withRev() }">History</RouterLink>
      <RouterLink v-if="store.repo?.has_layout" :to="{ name: 'layout', query: withRev() }">Layout 3D</RouterLink>
      <RouterLink
        v-if="store.repo?.has_layout || store.repo?.has_equipment_estimate"
        :to="{ name: 'mto', query: withRev() }"
        :title="store.repo?.has_layout ? 'Material take-off and estimate of the 3D model, equipment estimate' : 'Equipment estimate (cheme assess equipment)'"
        >MTO</RouterLink
      >
      <RouterLink v-if="store.repo?.has_lca" :to="{ name: 'lca', query: withRev() }" title="Life cycle assessment (cheme assess lca)">LCA</RouterLink>
      <RouterLink :to="{ name: 'about', query: withRev() }" title="About cheme-as-code and Process Intelligence Research">About</RouterLink>
    </nav>

    <span
      v-if="store.snapshot"
      class="badge snapshot"
      :title="`Static snapshot written by ${store.snapshot.tool}${store.snapshot.dirty ? ' from a working tree with uncommitted changes' : ''}`"
      data-testid="snapshot-badge"
    >
      Snapshot {{ store.snapshot.commit ? shortRev(store.snapshot.commit) : "" }}{{ store.snapshot.dirty ? " +changes" : "" }}
    </span>
    <div v-else class="rev">
      <label class="sr-only" for="rev-select">Revision</label>
      <form v-if="showCustom" class="custom" @submit.prevent="applyCustom">
        <input
          id="rev-select"
          v-model="customRev"
          type="text"
          placeholder="branch, tag or sha"
          autocomplete="off"
          spellcheck="false"
          @keydown.esc="showCustom = false"
        />
        <button class="btn" type="submit">Go</button>
      </form>
      <template v-else>
        <select id="rev-select" :value="rev ?? ''" title="Revision shown" @change="onSelect">
          <option v-for="o in options" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <button class="btn" type="button" title="Show another revision (tag or commit)" @click="openCustom">
          &hellip;
        </button>
      </template>
    </div>
  </header>
</template>

<style scoped>
.badge.snapshot {
  margin-left: auto;
  background: var(--info-soft);
  color: var(--info);
}
.badge.stage,
.badge.maturity {
  flex: 0 1 auto;
  min-width: 0;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.badge.maturity:hover {
  text-decoration: underline;
}
.badge-key {
  font-weight: 400;
}
.header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 0 var(--space-4);
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  min-width: 0;
}
.menu {
  display: none;
}
.brand {
  color: var(--fg);
  font-weight: 700;
  font-size: var(--text-lg);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.brand .logo {
  flex: none;
}
.brand .name {
  overflow: hidden;
  text-overflow: ellipsis;
}
.brand:hover {
  text-decoration: none;
}
.nav {
  display: flex;
  gap: var(--space-3);
  margin-left: var(--space-3);
  min-width: 0;
  overflow-x: auto;
  scrollbar-width: none;
}
.nav a {
  white-space: nowrap;
  color: var(--fg-muted);
  padding: 4px 2px;
  border-bottom: 2px solid transparent;
}
.nav a.router-link-active {
  color: var(--fg);
  border-bottom-color: var(--accent);
}
.nav a:hover {
  text-decoration: none;
  color: var(--fg);
}
.rev {
  margin-left: auto;
  display: flex;
  gap: var(--space-1);
  min-width: 0;
  /* The nav scrolls; the revision picker keeps its width (it overflowed the header on phones). */
  flex-shrink: 0;
}
.rev select {
  max-width: 260px;
}
.custom {
  display: flex;
  gap: var(--space-1);
}
.custom input {
  width: 180px;
}

@media (max-width: 860px) {
  .menu {
    display: inline-flex;
  }
}
@media (max-width: 640px) {
  .header {
    gap: var(--space-2);
    padding: 0 var(--space-2);
  }
  .nav {
    margin-left: 0;
    gap: var(--space-2);
    font-size: var(--text-sm);
  }
  /* On phones both are on the overview and the Maturity page (the nav keeps its link). */
  .badge.stage,
  .badge.maturity {
    display: none;
  }
  .rev select {
    max-width: 110px;
  }
  .custom input {
    width: 110px;
  }
}
@media (max-width: 480px) {
  .brand,
  .rev .btn {
    display: none;
  }
  .rev select {
    max-width: 104px;
  }
}
</style>
