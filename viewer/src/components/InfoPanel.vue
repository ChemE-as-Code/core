<script setup lang="ts">
import type { Picked } from "./SvgPane.vue";
import type { Change } from "@/api";

/** `issue`: the "New issue about <tag>" link (when the plant tracks issues). */
defineProps<{ picked: Picked | null; changes?: Change[]; issue?: { url: string; tag: string } | null }>();
defineEmits<{ close: [] }>();
</script>

<template>
  <aside v-if="picked" class="info" aria-live="polite">
    <header>
      <strong>Selected object</strong>
      <button class="btn close" type="button" aria-label="Close" @click="$emit('close')">&times;</button>
    </header>
    <dl>
      <dt>id</dt>
      <dd><code>{{ picked.id }}</code></dd>
      <template v-if="picked.className">
        <dt>class</dt>
        <dd>{{ picked.className }}</dd>
      </template>
      <template v-if="picked.texts.length">
        <dt>labels</dt>
        <dd>{{ picked.texts.join(" · ") }}</dd>
      </template>
    </dl>
    <a v-if="issue" class="btn issue" :href="issue.url" target="_blank" rel="noopener" data-action="new-issue">New issue about {{ issue.tag }}</a>
    <template v-if="changes && changes.length">
      <strong>Changes</strong>
      <ul class="changes">
        <li v-for="(c, i) in changes" :key="i">
          <span class="badge" :class="c.kind">{{ c.kind }}</span>
          {{ c.object_type }} <code>{{ c.object_id }}</code>
          <span v-if="c.detail" class="muted"> &mdash; {{ c.detail }}</span>
        </li>
      </ul>
    </template>
  </aside>
</template>

<style scoped>
.info {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 3;
  width: min(340px, calc(100% - 16px));
  max-height: calc(100% - 64px);
  overflow: auto;
  padding: var(--space-3);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  font-size: var(--text-sm);
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-2);
}
.close {
  min-height: 24px;
  padding: 0 8px;
}
dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px var(--space-3);
  margin: 0 0 var(--space-2);
}
dt {
  color: var(--fg-muted);
}
dd {
  margin: 0;
  word-break: break-word;
}
.issue {
  display: inline-flex;
  margin-bottom: var(--space-2);
}
.issue:hover {
  text-decoration: none;
}
.changes {
  margin: var(--space-1) 0 0;
  padding-left: 0;
  list-style: none;
  display: grid;
  gap: 4px;
}
</style>
