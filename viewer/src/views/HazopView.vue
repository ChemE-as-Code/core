<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import LoadState from "@/components/LoadState.vue";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { shortRev } from "@/lib/format";
import { HAZOP_DIR, loadStudies, refLabel, studyTotals, worksheetRows, type HazopEntry, type HazopRating } from "@/lib/hazop";

const { rev, withRev } = useRev();
const route = useRoute();
const router = useRouter();

const studies = useAsync<HazopEntry[]>((signal) => loadStudies(rev.value, signal), rev);
const all = computed(() => studies.data.value ?? []);
// `?study=H-01` picks one; the first study otherwise.
const selected = computed(() => all.value.find((e) => e.id === route.query.study) ?? all.value[0] ?? null);
const study = computed(() => selected.value?.study ?? null);
const totals = computed(() => (study.value ? studyTotals(study.value) : null));
const safeguardTitle = computed(() => new Map((study.value?.safeguards ?? []).map((s) => [s.id, s.title ?? s.id])));
const actionText = computed(() => new Map((study.value?.actions ?? []).map((a) => [a.id, a.text ?? a.id])));

function pick(id: string): void {
  void router.replace({ query: { ...route.query, study: id } });
}
const statusOf = (s?: string) => s ?? "proposed";
const ratingText = (r: HazopRating) => `${r.category}: ${r.severity ?? "?"}${r.likelihood ?? "?"}${r.band?.value ? ` ${r.band.value}` : ""}`;
</script>

<template>
  <div class="page hazop">
    <h1>
      HAZOP
      <small>{{ HAZOP_DIR }}/{{ rev ? ` at ${shortRev(rev)}` : " in the working tree" }}</small>
    </h1>
    <p class="muted hint">
      The studies of <code>{{ HAZOP_DIR }}/&lt;id&gt;/study.yaml</code> as worksheets, read only. An entry stays
      <span class="badge warning">proposed</span> until the team accepts it; <code>cheme safety hazop check</code> gives the findings.
    </p>

    <LoadState :loading="studies.loading.value && !studies.data.value" :error="studies.error.value" @retry="studies.reload" />

    <template v-if="studies.data.value">
      <p v-if="!all.length" class="notice" data-empty>No HAZOP study in <code>{{ HAZOP_DIR }}/</code> at this revision.</p>
      <template v-else>
        <div v-if="all.length > 1" class="toolbar">
          <label for="hazop-study">Study</label>
          <select id="hazop-study" :value="selected?.id" @change="pick(($event.target as HTMLSelectElement).value)">
            <option v-for="e in all" :key="e.id" :value="e.id">{{ e.id }}{{ e.study?.title ? ` – ${e.study.title}` : "" }}</option>
          </select>
        </div>

        <p v-if="selected?.error" class="bad">{{ selected.path }}: {{ selected.error }}</p>

        <template v-if="study && totals">
          <h2>
            {{ study.id }} {{ study.title }}
            <span v-if="study.example" class="badge info">example</span>
            <RouterLink class="small" :to="{ name: 'yaml', params: { path: selected!.path.split('/') }, query: withRev() }">study.yaml</RouterLink>
          </h2>

          <div class="cards" aria-label="Totals">
            <div class="card"><span class="card-title">nodes</span><span class="card-value" data-total="nodes">{{ totals.nodes }}</span></div>
            <div class="card"><span class="card-title">scenarios</span><span class="card-value" data-total="scenarios">{{ totals.scenarios }}</span></div>
            <div class="card" title="Nodes, scenarios and safeguards the team has not accepted">
              <span class="card-title">proposed</span><span class="card-value" :class="{ warn: totals.proposed }" data-total="proposed">{{ totals.proposed }}</span>
            </div>
            <div class="card"><span class="card-title">open actions</span><span class="card-value" data-total="actions">{{ totals.openActions }}</span></div>
          </div>

          <dl class="meta">
            <template v-if="study.scope"><dt>Scope</dt><dd>{{ study.scope }}</dd></template>
            <template v-if="study.modes?.length"><dt>Modes</dt><dd>{{ study.modes.map((m) => m.title ?? m.id).join(", ") }}</dd></template>
            <template v-if="study.team?.length"><dt>Team</dt><dd>{{ study.team.map((t) => (t.role ? `${t.name} (${t.role})` : t.name)).join(", ") }}</dd></template>
            <template v-if="study.risk_matrix"><dt>Risk matrix</dt><dd><code>{{ study.risk_matrix }}</code></dd></template>
            <template v-if="study.assessment_basis"><dt>Assessment</dt><dd>{{ study.assessment_basis }}</dd></template>
            <template v-if="study.analysed?.length"><dt>Analysed</dt><dd><code v-for="a in study.analysed" :key="a.path" class="analysed">{{ a.path }}</code></dd></template>
          </dl>

          <section v-for="node in study.nodes ?? []" :key="node.id" class="node" :data-node="node.id">
            <h3>
              {{ node.id }} {{ node.title }}
              <span class="badge" :class="statusOf(node.status) === 'accepted' ? 'clean' : 'warning'">{{ statusOf(node.status) }}</span>
            </h3>
            <p v-if="node.design_intent"><strong>Design intent:</strong> {{ node.design_intent }}</p>
            <p v-if="node.members?.length" class="small"><strong>Members:</strong> {{ node.members.map(refLabel).join(", ") }}</p>
            <p v-if="node.notes" class="muted small">{{ node.notes }}</p>
            <div class="table-wrap">
              <table class="data" :aria-label="`Worksheet of ${node.id}`">
                <thead>
                  <tr><th>deviation</th><th>id</th><th>cause</th><th>consequence</th><th>safeguards</th><th>actions</th><th>risk</th><th>status</th></tr>
                </thead>
                <tbody>
                  <tr v-for="row in worksheetRows(node)" :key="`${row.deviation.id}-${row.scenario?.id ?? ''}`" :data-scenario="row.scenario?.id">
                    <td v-if="row.first" :rowspan="row.span" class="nowrap">
                      <strong>{{ row.deviation.guide_word }} {{ row.deviation.parameter }}</strong>
                      <div class="faint">{{ row.deviation.id }}</div>
                    </td>
                    <template v-if="row.scenario">
                      <td class="nowrap">{{ row.scenario.id }}</td>
                      <td>{{ row.scenario.cause }}</td>
                      <td>
                        {{ row.scenario.consequence }}
                        <div v-if="row.scenario.notes" class="muted small">{{ row.scenario.notes }}</div>
                      </td>
                      <td><div v-for="id in row.scenario.safeguards ?? []" :key="id" :title="safeguardTitle.get(id)"><code>{{ id }}</code> {{ safeguardTitle.get(id) }}</div></td>
                      <td><div v-for="id in row.scenario.actions ?? []" :key="id"><code>{{ id }}</code> {{ actionText.get(id) }}</div></td>
                      <td class="small nowrap">
                        <div v-for="r in row.scenario.risk?.initial ?? []" :key="`i-${r.category}`" title="initial (before safeguards)">{{ ratingText(r) }}</div>
                        <div v-for="r in row.scenario.risk?.residual ?? []" :key="`r-${r.category}`" class="muted" title="residual (with safeguards)">→ {{ ratingText(r) }}</div>
                        <span v-if="!row.scenario.risk?.initial?.length" class="faint">unrated</span>
                      </td>
                      <td><span class="badge" :class="statusOf(row.scenario.status) === 'accepted' ? 'clean' : 'warning'">{{ statusOf(row.scenario.status) }}</span></td>
                    </template>
                    <td v-else colspan="7" class="muted">{{ row.deviation.notes ?? "No scenario." }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section v-if="study.safeguards?.length" aria-label="Safeguards">
            <h3>Safeguards</h3>
            <table class="data">
              <thead><tr><th>id</th><th>safeguard</th><th>kind</th><th>refs</th><th>status</th></tr></thead>
              <tbody>
                <tr v-for="s in study.safeguards" :key="s.id" :data-safeguard="s.id">
                  <td>{{ s.id }}</td><td>{{ s.title }}</td><td>{{ s.kind }}{{ s.interlock ? ` ${s.interlock}` : "" }}</td>
                  <td>{{ (s.refs ?? []).map(refLabel).join(", ") }}</td><td>{{ statusOf(s.status) }}</td>
                </tr>
              </tbody>
            </table>
          </section>

          <section v-if="study.actions?.length" aria-label="Actions">
            <h3>Actions</h3>
            <table class="data">
              <thead><tr><th>id</th><th>action</th><th>owner</th><th>status</th></tr></thead>
              <tbody>
                <tr v-for="a in study.actions" :key="a.id" :data-action="a.id">
                  <td>{{ a.id }}</td><td>{{ a.text }}</td><td>{{ a.owner }}</td><td>{{ statusOf(a.status) }}</td>
                </tr>
              </tbody>
            </table>
          </section>
        </template>
      </template>
    </template>
  </div>
</template>

<style scoped>
.hint {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
  max-width: 80ch;
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}
.card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  font-size: var(--text-sm);
}
.card-title {
  color: var(--fg-muted);
}
.card-value {
  font-size: var(--text-lg);
  font-variant-numeric: tabular-nums;
}
.meta {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: var(--space-1) var(--space-3);
  font-size: var(--text-sm);
  max-width: 100ch;
}
.meta dt {
  color: var(--fg-muted);
}
.meta dd {
  margin: 0;
}
.analysed + .analysed {
  margin-left: var(--space-2);
}
.node {
  margin-top: var(--space-4);
}
.node p {
  max-width: 100ch;
}
td {
  vertical-align: top;
}
.nowrap {
  white-space: nowrap;
}
.small {
  font-size: var(--text-sm);
}
.warn {
  color: var(--warn);
  font-weight: 600;
}
.bad {
  color: var(--bad);
  font-weight: 600;
}
</style>
