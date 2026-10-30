<script setup lang="ts">
/**
 * The root of a library server (`cheme serve` on a folder of plants, core's ADR 0034): its
 * plants as cards, filterable, each opening the viewer of that plant at `/p/<id>/`. The
 * `process.yaml` fields (title, summary, families) show when a plant has them; nothing here
 * depends on them.
 */
import { computed, ref, watchEffect } from "vue";
import type { PlantsIndex } from "@/api";
import { filterPlants, plantName, switchUrl } from "@/lib/plants";
import { levelName } from "@/lib/maturity";

const props = defineProps<{ index: PlantsIndex }>();
const logo = `${import.meta.env.BASE_URL}logo.svg`;
const text = ref("");
const family = ref("");
const stage = ref("");

const families = computed(() => [...new Set(props.index.plants.flatMap((p) => p.families))].sort());
const stages = computed(() => [...new Set(props.index.plants.flatMap((p) => (p.stage ? [p.stage] : [])))].sort());
const shown = computed(() => filterPlants(props.index.plants, { text: text.value, family: family.value, stage: stage.value }));
const href = (id: string) => switchUrl(id, { name: "home", path: "/" }, window.location.search);

watchEffect(() => (document.title = `Plants – ${props.index.root_name} – cheme-as-code viewer`));
</script>

<template>
  <div class="plants-app">
    <header class="header">
      <img class="logo" :src="logo" alt="" width="34" height="34" />
      <span class="name">{{ index.root_name }}</span>
      <span class="muted">{{ index.plants.length }} plants</span>
    </header>
    <main id="main" class="page">
      <h1>Plants <small>{{ index.root_name }}</small></h1>
      <div class="toolbar">
        <input v-model="text" type="search" placeholder="Filter plants" aria-label="Filter plants" data-testid="plants-filter" />
        <select v-if="families.length" v-model="family" aria-label="Family">
          <option value="">every family</option>
          <option v-for="f in families" :key="f" :value="f">{{ f }}</option>
        </select>
        <select v-if="stages.length > 1" v-model="stage" aria-label="Stage">
          <option value="">every stage</option>
          <option v-for="s in stages" :key="s" :value="s">{{ s }}</option>
        </select>
        <span class="muted">{{ shown.length }} of {{ index.plants.length }}</span>
      </div>
      <ul class="cards" aria-label="Plants">
        <li v-for="p in shown" :key="p.id">
          <a class="card" :href="href(p.id)" :data-plant="p.id">
            <strong>{{ plantName(p) }}</strong>
            <span class="meta">
              <code>{{ p.path }}</code>
              <span v-if="p.stage" class="badge stage">{{ p.stage }}</span>
              <span v-if="p.maturity" class="badge pass" :title="p.maturity_checked ? `recorded ${p.maturity_checked}` : 'recorded'">{{ levelName(p.maturity) }}</span>
              <span v-if="p.sheets" class="faint">{{ p.sheets }} sheets</span>
            </span>
            <span v-if="p.title && p.title !== plantName(p)" class="title">{{ p.title }}</span>
            <span v-if="p.summary" class="summary muted">{{ p.summary }}</span>
            <span v-if="p.error" class="notice warning small">{{ p.error }}</span>
            <span v-if="p.families.length" class="families">
              <span v-for="f in p.families" :key="f" class="badge">{{ f }}</span>
            </span>
          </a>
        </li>
        <li v-if="!shown.length" class="muted">No plant matches.</li>
      </ul>
    </main>
  </div>
</template>

<style scoped>
.plants-app {
  min-height: 100%;
  background: var(--bg);
}
.header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  height: var(--header-h);
  padding: 0 var(--space-4);
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.name {
  font-weight: 700;
  font-size: var(--text-lg);
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-3);
  list-style: none;
  margin: var(--space-3) 0 0;
  padding: 0;
}
.card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  height: 100%;
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
.meta,
.families {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px var(--space-2);
  font-size: var(--text-sm);
}
.summary {
  font-size: var(--text-sm);
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  overflow: hidden;
}
.small {
  font-size: var(--text-sm);
  margin: 0;
}
</style>
