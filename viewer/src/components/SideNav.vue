<script setup lang="ts">
// The sidebar: the plant's pages and documents in engineering groups (src/lib/pages.ts), then
// the raw repository files, folded away by default (for experts).
import { computed } from "vue";
import { useRoute } from "vue-router";
import FileTree from "@/components/FileTree.vue";
import { useRev } from "@/lib/useRev";
import { paramPath } from "@/lib/format";
import { isCurrent, navFiles } from "@/lib/pages";
import { useNavGroups } from "@/lib/useNavGroups";

const route = useRoute();
const { withRev } = useRev();
const groups = useNavGroups();
const files = computed(() => navFiles(groups.value));
const current = computed(() => ({
  name: String(route.name ?? ""),
  path: paramPath(route.params.path),
  tab: typeof route.query.tab === "string" ? route.query.tab : null,
}));
// a group's heading opens its section page (`/section/<id>`)
const sectionShown = (id: string) => route.name === "section" && route.params.id === id;
</script>

<template>
  <div class="tree">
    <nav aria-label="Pages">
      <RouterLink class="row overview" :class="{ active: route.name === 'home' }" :to="{ name: 'home', query: withRev() }">
        <span class="label">Overview</span>
      </RouterLink>
      <section v-for="group in groups" :key="group.id" :data-group="group.id">
        <h2>
          <RouterLink
            class="heading"
            :class="{ active: sectionShown(group.id) }"
            :aria-current="sectionShown(group.id) ? 'page' : undefined"
            :to="{ name: 'section', params: { id: group.id }, query: withRev() }"
            >{{ group.title }}</RouterLink
          >
        </h2>
        <ul class="list">
          <li v-for="item in group.items" :key="item.key">
            <RouterLink
              class="row"
              :class="{ active: isCurrent(item, current) }"
              :aria-current="isCurrent(item, current) ? 'page' : undefined"
              :to="{ ...item.to, query: withRev(item.to.query) }"
              :title="item.title"
            >
              <span class="label">{{ item.label }}<span v-if="item.detail" class="muted detail">{{ item.detail }}</span></span>
              <span v-if="item.badge" class="kind" :class="item.badge.toLowerCase()">{{ item.badge }}</span>
            </RouterLink>
          </li>
        </ul>
      </section>
    </nav>
    <FileTree :nav-files="files" />
  </div>
</template>

<style scoped>
.tree {
  padding: var(--space-2) 0 var(--space-6);
  font-size: var(--text-sm);
}
h2 {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--fg-muted);
  margin: var(--space-3) var(--space-3) var(--space-1);
}
h2 .heading {
  display: block;
  /* padded so the current page's background does not touch the text, pulled back to stay aligned */
  padding: 1px 4px;
  margin: 0 -4px;
  color: inherit;
  border-radius: 3px;
}
/* a cue that the heading opens a page, also without hover (phones); in CSS so the text stays the title */
h2 .heading::after {
  content: "\203A" / ""; /* decorative: not part of the link's name */
  margin-left: 0.4em;
  font-size: 13px;
  line-height: 1;
}
h2 .heading:hover {
  color: var(--accent);
  text-decoration: none;
}
h2 .heading.active {
  color: var(--accent);
  background: var(--accent-soft);
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
  padding: 3px var(--space-3) 3px 12px;
  color: var(--fg);
  border-left: 3px solid transparent;
  min-height: 26px;
}
.row:hover {
  background: var(--bg-sunk);
  text-decoration: none;
}
.row.active {
  background: var(--accent-soft);
  border-left-color: var(--accent);
}
.row.active > .label {
  font-weight: 600;
}
.detail {
  margin-left: 0.35em;
}
.overview {
  font-weight: 600;
}
.label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
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
</style>
