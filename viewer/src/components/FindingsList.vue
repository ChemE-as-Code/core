<script setup lang="ts">
/** A list of findings (level, rule, message, hint), each linking the file at its line. */
import type { Finding } from "@/api";
import { useRev } from "@/lib/useRev";
import { pathSegments } from "@/lib/format";

const props = withDefaults(
  defineProps<{
    findings: readonly Finding[];
    label: string;
    title?: string;
    /** False: the findings are of the working tree, so the file links open the working tree, not `?rev=`. */
    atRev?: boolean;
  }>(),
  { atRev: true },
);
const { withRev } = useRev();
const fileQuery = (line: number | null | undefined) => {
  const extra = line ? { line: String(line) } : {};
  return props.atRev ? withRev(extra) : extra;
};
</script>

<template>
  <section v-if="findings.length" class="findings" :aria-label="label">
    <h2>{{ title ?? "Findings" }} <span class="muted">{{ findings.length }}</span></h2>
    <ul>
      <li v-for="(f, i) in findings" :key="f.id ?? i" :data-rule="f.rule">
        <span class="badge" :class="f.level">{{ f.level }}</span>
        <code class="rule">{{ f.rule.replace(/^cheme\./, "") }}</code>
        {{ f.message }}
        <span v-if="f.hint" class="muted finding-hint">{{ f.hint }}</span>
        <RouterLink class="file" :to="{ name: 'file', params: { path: pathSegments(f.file) }, query: fileQuery(f.line) }">{{ f.file }}<template v-if="f.line">:{{ f.line }}</template></RouterLink>
      </li>
    </ul>
  </section>
</template>

<style scoped>
h2 {
  font-size: var(--text-md, 15px);
  margin: var(--space-4) 0 var(--space-2);
}
ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  font-size: var(--text-sm);
  overflow-wrap: anywhere;
}
.rule {
  margin: 0 var(--space-1);
}
.finding-hint {
  display: block;
  margin-left: var(--space-4);
  font-size: 11.5px;
}
.file {
  margin-left: var(--space-2);
}
</style>
