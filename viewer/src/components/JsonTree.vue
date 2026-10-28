<script setup lang="ts">
import { computed, ref } from "vue";

defineOptions({ name: "JsonTree" });

const props = withDefaults(defineProps<{ value: unknown; name?: string | number | null; depth?: number }>(), {
  name: null,
  depth: 0,
});

const isArray = computed(() => Array.isArray(props.value));
const isObject = computed(() => typeof props.value === "object" && props.value !== null);
const entries = computed<[string | number, unknown][]>(() => {
  const value = props.value;
  if (Array.isArray(value)) return value.map((v, i) => [i, v]);
  if (typeof value === "object" && value !== null) return Object.entries(value);
  return [];
});
const countLabel = computed(() => (isArray.value ? `[${entries.value.length}]` : `{${entries.value.length}}`));
const open = ref(props.depth < 2);

const scalar = computed(() => {
  const v = props.value;
  if (v === null || v === undefined) return { text: "null", cls: "null" };
  if (typeof v === "string") return { text: v, cls: "string" };
  if (typeof v === "number") return { text: String(v), cls: "number" };
  if (typeof v === "boolean") return { text: String(v), cls: "boolean" };
  return { text: String(v), cls: "" };
});
</script>

<template>
  <div class="node">
    <template v-if="isObject">
      <button type="button" class="toggle" :aria-expanded="open" @click="open = !open">
        <span class="caret">{{ open ? "▾" : "▸" }}</span>
        <span v-if="name !== null" class="key">{{ name }}</span>
        <span class="faint">{{ countLabel }}</span>
      </button>
      <div v-if="open" class="children">
        <JsonTree v-for="[key, child] in entries" :key="key" :value="child" :name="key" :depth="depth + 1" />
        <div v-if="!entries.length" class="faint">empty</div>
      </div>
    </template>
    <div v-else class="leaf">
      <span v-if="name !== null" class="key">{{ name }}:</span>
      <span class="value" :class="scalar.cls">{{ scalar.text }}</span>
    </div>
  </div>
</template>

<style scoped>
.node {
  font-size: var(--text-sm);
  line-height: 1.6;
}
.toggle {
  border: 0;
  background: none;
  padding: 0;
  cursor: pointer;
  display: inline-flex;
  gap: 4px;
  align-items: baseline;
}
.caret {
  color: var(--fg-muted);
  width: 12px;
}
.children {
  padding-left: 16px;
  border-left: 1px solid var(--border);
  margin-left: 5px;
}
.leaf {
  padding-left: 16px;
  word-break: break-word;
}
.key {
  font-weight: 600;
  margin-right: 4px;
}
.string {
  color: var(--ok);
  white-space: pre-wrap;
}
.number,
.boolean {
  color: var(--info);
}
.null {
  color: var(--fg-faint);
  font-style: italic;
}
</style>
