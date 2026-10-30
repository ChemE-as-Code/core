<script setup lang="ts">
/** A list of findings (level, rule, message, hint), each linking the file at its line. */
import type { Finding } from "@/api";
import { computed } from "vue";
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
// Info findings (notes, often dozens) fold away when there are more than a few (#67); errors and
// warnings stay in view.
const INFO_FOLD = 5;
const shown = computed(() => (infos.value.length > INFO_FOLD ? props.findings.filter((f) => f.level !== "info") : props.findings));
const infos = computed(() => props.findings.filter((f) => f.level === "info"));
const fileQuery = (line: number | null | undefined) => {
  const extra = line ? { line: String(line) } : {};
  return props.atRev ? withRev(extra) : extra;
};
</script>

<template>
  <section v-if="findings.length" class="findings" :aria-label="label">
    <h2>{{ title ?? "Findings" }} <span class="muted">{{ findings.length }}</span></h2>
    <ul>
      <li v-for="(f, i) in shown" :key="f.id ?? i" :data-rule="f.rule">
        <span class="badge" :class="f.level">{{ f.level }}</span>
        <code class="rule">{{ f.rule.replace(/^cheme\./, "") }}</code>
        {{ f.message }}
        <span v-if="f.hint" class="muted finding-hint">{{ f.hint }}</span>
        <RouterLink class="file" :to="{ name: 'file', params: { path: pathSegments(f.file) }, query: fileQuery(f.line) }">{{ f.file }}<template v-if="f.line">:{{ f.line }}</template></RouterLink>
      </li>
    </ul>
    <details v-if="infos.length > INFO_FOLD" class="infos" data-testid="info-findings">
      <summary>{{ infos.length }} info findings</summary>
      <ul>
        <li v-for="(f, i) in infos" :key="f.id ?? i" :data-rule="f.rule">
          <span class="badge info">info</span>
          <code class="rule">{{ f.rule.replace(/^cheme\./, "") }}</code>
          {{ f.message }}
          <span v-if="f.hint" class="muted finding-hint">{{ f.hint }}</span>
          <RouterLink class="file" :to="{ name: 'file', params: { path: pathSegments(f.file) }, query: fileQuery(f.line) }">{{ f.file }}<template v-if="f.line">:{{ f.line }}</template></RouterLink>
        </li>
      </ul>
    </details>
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
.infos {
  margin-top: var(--space-2);
  font-size: var(--text-sm);
}
.infos summary {
  cursor: pointer;
  color: var(--fg-muted);
}
.infos ul {
  margin-top: var(--space-1);
}
</style>
