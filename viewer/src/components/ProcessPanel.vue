<script setup lang="ts">
import { computed } from "vue";
import type { StreamTable } from "@/api";
import type { Picked } from "./SvgPane.vue";
import ProcessValueCell from "./ProcessValueCell.vue";
import { BALANCE_BADGE, PROVENANCE_SHORT, balanceDetail, formatComposition, formatPhase, pickInfo } from "@/lib/process";

/** `issue`: the "New issue about <id>" link (when the plant tracks issues). */
const props = defineProps<{ picked: Picked | null; table: StreamTable | null; sheetKind?: string | undefined; error?: string | null; issue?: { url: string; tag: string } | null }>();
defineEmits<{ close: [] }>();

const info = computed(() => (props.picked && props.table ? pickInfo(props.table, props.sheetKind, props.picked.id) : null));
const title = computed(() => {
  const i = info.value;
  if (!i) return "Selected object";
  if (i.kind === "connection") return `BFD connection ${i.id}${i.streams.length > 1 ? " (aggregated)" : ""}`;
  if (i.kind === "stream") return `Stream ${i.id}`;
  if (i.kind === "node") return `${i.node!.kind} ${i.id}`;
  return "Selected object";
});
</script>

<template>
  <aside v-if="picked" class="info process-panel" aria-live="polite">
    <header>
      <strong>{{ title }}</strong>
      <button class="btn close" type="button" aria-label="Close" @click="$emit('close')">&times;</button>
    </header>
    <a v-if="issue" class="btn issue" :href="issue.url" target="_blank" rel="noopener" data-action="new-issue">New issue about {{ issue.tag }}</a>
    <p v-if="error" class="notice error">{{ error }}</p>
    <p v-else-if="!table" class="muted loading">Loading the stream table…</p>
    <template v-if="info">
      <p v-if="info.node?.title" class="muted">{{ info.node.title }}<span v-if="info.node.block"> · in block {{ info.node.block }}</span></p>
      <p v-if="info.balance" class="balance">
        balance <span class="badge" :class="BALANCE_BADGE[info.balance.status]">{{ info.balance.status }}</span>
        <span class="muted">{{ balanceDetail(info.balance) }}</span>
      </p>
      <p v-if="info.kind === 'connection'" class="muted">Represents {{ info.streams.length }} stream{{ info.streams.length === 1 ? "" : "s" }}:</p>
      <p v-else-if="info.kind === 'unknown'" class="muted">
        <code>{{ picked.id }}</code> is not a stream, block or step of the flowsheet.
      </p>
      <section v-for="s in info.streams" :key="s.id" class="stream" :data-stream="s.id" :class="{ error: s.imbalance.length }">
        <h3>
          {{ s.id }} <span class="muted">{{ s.title }}</span>
          <span v-if="!s.on_bfd" class="badge info">internal</span>
          <span v-if="s.imbalance.length" class="badge fail">balance {{ s.imbalance.join(", ") }}</span>
        </h3>
        <div class="mono muted">{{ s.from }} → {{ s.to }}</div>
        <dl>
          <template v-for="(v, name) in s.properties" :key="name">
            <template v-if="v">
              <dt>{{ name }}</dt>
              <dd><ProcessValueCell :value="v" /></dd>
            </template>
          </template>
          <template v-if="s.composition">
            <dt>composition</dt>
            <dd>{{ formatComposition(s) }} <span class="prov" :class="s.composition.provenance">{{ PROVENANCE_SHORT[s.composition.provenance] }}</span></dd>
          </template>
          <template v-if="s.phase">
            <dt>phase</dt>
            <dd>{{ formatPhase(s) }} <span v-if="s.phase.stale" class="badge warning">stale</span></dd>
          </template>
          <template v-for="(v, name) in s.calculated" :key="name">
            <dt>{{ name }}</dt>
            <dd><ProcessValueCell :value="v" /></dd>
          </template>
          <template v-if="s.links.length">
            <dt>links</dt>
            <dd>
              <span v-for="l in s.links" :key="l.target + l.ref" class="badge" :class="l.resolved ? 'pass' : 'info'" :title="l.problem ?? 'resolved'">{{ l.target }} {{ l.ref }}</span>
            </dd>
          </template>
        </dl>
        <p v-if="!s.has_state" class="muted">No values for this case.</p>
      </section>
      <p v-if="info.node && info.node.links.length" class="links">
        links:
        <span v-for="l in info.node.links" :key="l.target + l.ref" class="badge" :class="l.resolved ? 'pass' : 'info'" :title="l.problem ?? 'resolved'">{{ l.target }} {{ l.ref }}</span>
      </p>
      <RouterLink class="btn" :to="{ name: 'streams', query: { stream: info.streams[0]?.id } }">Stream table</RouterLink>
    </template>
  </aside>
</template>

<style scoped>
.issue {
  display: inline-flex;
  margin-bottom: var(--space-2);
}
.issue:hover {
  text-decoration: none;
}
.info {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 3;
  width: min(380px, calc(100% - 16px));
  max-height: calc(100% - 24px);
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
  text-transform: none;
}
.close {
  min-height: 24px;
  padding: 0 8px;
}
p {
  margin: 0 0 var(--space-2);
}
.stream {
  border-top: 1px solid var(--border);
  padding: var(--space-2) 0;
}
.stream.error h3 {
  color: var(--bad);
}
h3 {
  font-size: var(--text-sm);
  margin: 0 0 2px;
}
.mono {
  font-family: var(--mono);
  font-size: 12px;
}
dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 2px var(--space-3);
  margin: var(--space-1) 0 0;
}
dt {
  color: var(--fg-muted);
}
dd {
  margin: 0;
  word-break: break-word;
}
</style>
