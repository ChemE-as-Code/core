<script setup lang="ts">
// A section of the navigation (`/section/<id>`): its intro and its pages and documents as cards,
// the drawn sheets with a thumbnail of the drawing (src/lib/pages.ts).
import { computed, reactive, watch } from "vue";
import { useRoute } from "vue-router";
import { api } from "@/api";
import { store } from "@/store";
import { useRev } from "@/lib/useRev";
import { isDrawing, section } from "@/lib/pages";
import { useNavGroups } from "@/lib/useNavGroups";

const route = useRoute();
const { rev, withRev } = useRev();
const groups = useNavGroups();
const known = computed(() => section(String(route.params.id ?? "")));
// left out of the navigation when the plant has nothing in it
const group = computed(() => groups.value.find((g) => g.id === known.value?.id));
// Thumbnails that did not load (a sheet drawn only in the working tree, shown at an older revision):
// their frame is left out rather than shown as a blank box.
const failed = reactive(new Set<string>());
watch(rev, () => failed.clear());
</script>

<template>
  <div class="page">
    <template v-if="!known">
      <h1>Section not found</h1>
      <p class="muted notice" role="status" data-testid="section-notice">
        There is no section "{{ route.params.id }}". <RouterLink :to="{ name: 'home', query: withRev() }">Back to the overview</RouterLink>.
      </p>
    </template>
    <template v-else>
      <h1>{{ known.title }}</h1>
      <p class="intro">{{ known.intro }}</p>
      <div v-if="group" class="cards" data-testid="section-cards">
        <RouterLink
          v-for="item in group.items"
          :key="item.key"
          class="card"
          :data-item="item.key"
          :to="{ ...item.to, query: withRev(item.to.query) }"
        >
          <!-- decorative: the card's text names the sheet -->
          <span v-if="isDrawing(item) && !failed.has(item.key)" class="thumb">
            <img loading="lazy" :src="api.pidSvgUrl(item.file, rev)" alt="" @error="failed.add(item.key)" />
          </span>
          <strong
            >{{ item.label
            }}<span v-if="item.badge" class="badge" :class="{ stage: item.badge !== 'P&ID' }">{{ item.badge }}</span></strong
          >
          <span v-if="item.detail">{{ item.detail }}</span>
          <!-- a sheet's or document's tooltip names its file, shown below instead -->
          <span v-if="item.title && !item.file" class="muted description">{{ item.title }}</span>
          <code v-if="item.file" class="muted">{{ item.file }}</code>
        </RouterLink>
      </div>
      <!-- the documents and datasheets come with /api/tree, after the repo: only then is a section known to be empty -->
      <p v-else-if="store.repo && store.treeSettled" class="muted notice" role="status" data-testid="section-notice">
        This plant has nothing in {{ known.title }} yet. <RouterLink :to="{ name: 'home', query: withRev() }">Back to the overview</RouterLink>.
      </p>
      <p v-else-if="store.loading || store.repo" class="muted" role="status">Loading&hellip;</p>
    </template>
  </div>
</template>

<style scoped>
.notice a {
  text-decoration: underline;
}
.intro {
  max-width: 70ch;
  margin: 0 0 var(--space-4);
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--space-3);
  align-items: start; /* a card without a thumbnail keeps its own height */
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
  min-width: 0;
}
.card:hover {
  border-color: var(--accent);
  text-decoration: none;
}
.card code {
  overflow-wrap: anywhere;
}
.card strong .badge {
  margin-left: 0.4em;
}
.description {
  font-size: var(--text-sm);
}
.thumb {
  display: block;
  aspect-ratio: 3 / 2; /* closer to a drawing sheet than 4:3 */
  margin-bottom: var(--space-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: #fff; /* the drawings are black on white, also in the dark theme */
  overflow: hidden;
}
.thumb img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}
</style>
