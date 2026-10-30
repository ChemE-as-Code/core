<script setup lang="ts">
/** A YAML mapping as a readable document (src/lib/yamlDocument.ts); nested sections recurse. */
import JsonTree from "@/components/JsonTree.vue";
import type { DocBlock } from "@/lib/yamlDocument";

defineOptions({ name: "YamlDocument" });
withDefaults(defineProps<{ blocks: DocBlock[]; depth?: number }>(), { depth: 0 });
</script>

<template>
  <div class="yaml-doc" :class="`depth-${depth}`">
    <template v-for="(block, i) in blocks" :key="i">
      <dl v-if="block.kind === 'fields'" class="fields">
        <template v-for="f in block.fields" :key="f.key">
          <dt><code>{{ f.key }}</code></dt>
          <dd>{{ f.text }}</dd>
        </template>
      </dl>
      <section v-else-if="block.kind === 'section'" :data-key="block.key">
        <component :is="depth === 0 ? 'h2' : 'h3'">{{ block.title }}</component>
        <YamlDocument :blocks="block.blocks" :depth="depth + 1" />
      </section>
      <div v-else class="block" :data-key="block.key">
        <p class="block-key"><code>{{ block.key }}</code></p>
        <ul v-if="block.kind === 'list'" class="items">
          <li v-for="(item, j) in block.items" :key="j">{{ item }}</li>
        </ul>
        <div v-else-if="block.kind === 'table'" class="table-wrap">
          <table class="data">
            <thead>
              <tr><th v-for="c in block.columns" :key="c">{{ c }}</th></tr>
            </thead>
            <tbody>
              <tr v-for="(row, j) in block.rows" :key="j">
                <td v-for="(cell, k) in row" :key="k">{{ cell }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="tree">
          <JsonTree :value="block.value" />
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.yaml-doc.depth-0 {
  max-width: 1100px;
}
h2 {
  font-size: var(--text-lg);
  margin: var(--space-6) 0 var(--space-2);
  padding-bottom: 2px;
  border-bottom: 1px solid var(--border);
}
h3 {
  font-size: var(--text);
  margin: var(--space-3) 0 var(--space-1);
}
.fields {
  display: grid;
  grid-template-columns: minmax(120px, max-content) minmax(0, 1fr);
  gap: 2px var(--space-4);
  margin: 0 0 var(--space-2);
}
.fields dt {
  color: var(--fg-muted);
}
.fields dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.block {
  margin: 0 0 var(--space-3);
}
.block-key {
  margin: var(--space-2) 0 var(--space-1);
  color: var(--fg-muted);
}
.items {
  margin: 0;
  padding-left: var(--space-4);
}
.items li {
  margin: 2px 0;
}
.tree {
  padding: var(--space-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  overflow: auto;
}
</style>
