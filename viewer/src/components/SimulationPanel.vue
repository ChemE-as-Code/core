<script setup lang="ts">
/**
 * The simulation of the plant (`GET /api/simulation`): what `process/simulation.yaml` asks of the
 * simulator, the run `cheme process simulate --fill` recorded in `process/simulation-run.json`
 * (converged or not, when and from which inputs, stale or current) and one row per step or block.
 */
import { computed } from "vue";
import type { Finding, SimulationView } from "@/api";
import FindingsList from "@/components/FindingsList.vue";
import { store } from "@/store";
import { useRev } from "@/lib/useRev";
import { pathSegments } from "@/lib/format";
import { PROVENANCE_SHORT } from "@/lib/process";
import { RUN_BADGE, UNIT_STATUS, resultEntries, runState, runTime, specEntries, unitConvergence } from "@/lib/simulation";

const props = defineProps<{ view: SimulationView }>();
defineEmits<{ setCase: [id: string] }>();
const { withRev } = useRev();

const run = computed(() => props.view.run);
const state = computed(() => runState(props.view));
const badge = computed(() => RUN_BADGE[state.value]);
/** `dwsim 9.0.5.0`: the recorded run's simulator and version, else the spec's simulator. */
const simulatorText = computed(() => {
  const version = run.value?.simulator.version;
  return version ? `${run.value!.simulator.name || props.view.spec.simulator} ${version}` : props.view.spec.simulator;
});
const counts = computed(() => {
  const out = new Map<string, number>();
  for (const u of props.view.units) out.set(u.status, (out.get(u.status) ?? 0) + 1);
  return [...out.entries()];
});
const filledCount = computed(() => (run.value?.streams ?? []).reduce((n, s) => n + s.filled.length, 0));
/** The view's findings and the run's, each once. */
const findings = computed<Finding[]>(() => {
  const seen = new Set<string>();
  return [...props.view.findings, ...(run.value?.findings ?? [])].filter((f) => {
    const key = f.id ?? `${f.rule}|${f.message}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
});
const tolerance = computed(() =>
  Object.entries(props.view.spec.tolerance)
    .map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`)
    .join(", "),
);
const components = computed(() => Object.entries(props.view.spec.components));
const fileLink = (path: string) => ({ name: "file", params: { path: pathSegments(path) }, query: withRev() });
</script>

<template>
  <section class="simulation" aria-label="Simulation">
    <dl class="facts">
      <dt>Simulator</dt>
      <dd data-simulator>
        <span>{{ simulatorText }}</span>
        <RouterLink class="muted file" :to="fileLink(view.file)">{{ view.file }}</RouterLink>
      </dd>
      <dt>Property package</dt>
      <dd data-package>{{ view.spec.property_package }}</dd>
      <dt>Case</dt>
      <dd>
        <select v-if="view.cases.length > 1" :value="view.case ?? ''" aria-label="Simulation case" @change="$emit('setCase', ($event.target as HTMLSelectElement).value)">
          <option v-for="c in view.cases" :key="c" :value="c">{{ c }}</option>
        </select>
        <span v-else>{{ view.case ?? "–" }}</span>
      </dd>
      <dt>Run</dt>
      <dd class="run">
        <span class="badge" :class="badge.badge" :title="badge.title" data-run-state>{{ badge.label }}</span>
        <span v-if="view.stale" class="badge warning" data-stale-badge>stale</span>
        <template v-if="run">
          <span data-run-at>{{ runTime(run.run_at) }}</span>
          <span class="muted">{{ run.tool }}</span>
          <span v-if="run.iterations !== null" class="muted">{{ run.iterations }} iterations</span>
        </template>
      </dd>
      <template v-if="run">
        <dt>Inputs</dt>
        <dd data-inputs>
          <template v-if="run.inputs.commit">
            commit
            <RouterLink v-if="!store.snapshot" :to="{ name: 'home', query: { rev: run.inputs.commit } }" :title="`Show the plant at ${run.inputs.commit}`"><code>{{ run.inputs.commit.slice(0, 7) }}</code></RouterLink>
            <code v-else>{{ run.inputs.commit.slice(0, 7) }}</code>
          </template>
          <span v-else class="muted">no commit</span>
          <span v-if="run.inputs.dirty.length" class="muted"> with uncommitted changes to {{ run.inputs.dirty.join(", ") }}</span>
        </dd>
      </template>
    </dl>

    <p v-if="view.problem" class="notice error" role="note" data-problem>
      The flowsheet does not load: {{ view.problem }}. The spec and the recorded run are shown; whether the run is stale cannot be told.
    </p>
    <div v-if="!run" class="notice" data-no-run>
      <p><strong>No run recorded{{ view.case ? ` for case ${view.case}` : "" }}.</strong></p>
      <p class="muted">
        <code>cheme process simulate --fill</code> runs {{ view.spec.simulator }}, writes the simulated values into <code>process/flowsheet.yaml</code> and records the run in
        <code>{{ view.run_file }}</code>; commit both.
      </p>
    </div>
    <div v-else-if="view.stale" class="notice warning" role="note" data-stale>
      <p><strong>The recorded run is stale:</strong> the feeds, specs, property package or simulator model changed since it ran. Run <code>cheme process simulate --fill</code> again.</p>
      <p v-if="view.staleness.changed_files.length" class="changed">
        Changed since:
        <RouterLink v-for="f in view.staleness.changed_files" :key="f" :to="fileLink(f)" data-changed-file>{{ f }}</RouterLink>
      </p>
    </div>
    <p v-else-if="view.staleness.changed_files.length" class="muted hint" data-changed>
      Changed since the run, the simulator model the same: {{ view.staleness.changed_files.join(", ") }}.
    </p>
    <p v-if="state === 'failed'" class="notice error" role="note" data-failed>
      The run did not converge<template v-if="run?.messages.length">: {{ run.messages.join("; ") }}</template>. No stream value was written.
    </p>
    <p v-if="run && state === 'converged'" class="muted hint" data-filled-count>
      {{ filledCount }} stream value{{ filledCount === 1 ? "" : "s" }} hold the simulated value (marked <span class="sim-mark">sim</span> in the stream table).
    </p>

    <p class="muted hint spec-line">
      <span v-if="tolerance">Tolerance: {{ tolerance }}.</span>
      <span v-if="view.spec.tear_streams.length"> Tear streams: {{ view.spec.tear_streams.join(", ") }}.</span>
      <span v-if="view.spec.exclude.length" data-exclude> Excluded: {{ view.spec.exclude.join(", ") }}.</span>
      <span v-if="components.length"> Components: {{ components.map(([k, v]) => `${k} = ${v}`).join(", ") }}.</span>
    </p>

    <h2>
      Units
      <span class="muted counts"><template v-for="([status, n], i) in counts" :key="status">{{ i ? ", " : "" }}{{ n }} {{ status }}</template></span>
    </h2>
    <div class="table-wrap">
      <table class="data units" aria-label="Simulation units">
        <thead>
          <tr>
            <th>Unit</th>
            <th>Status</th>
            <th>Spec</th>
            <th>Results</th>
            <th>Notes</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in view.units" :key="u.id" :data-unit="u.id" :data-status="u.status">
            <td class="id-cell">
              <strong>{{ u.id }}</strong>
              <span v-if="u.unit" class="muted type">{{ u.unit.replace(/_/g, " ") }}</span>
            </td>
            <td class="status">
              <span class="badge" :class="UNIT_STATUS[u.status].badge" :title="UNIT_STATUS[u.status].title">{{ u.status }}</span>
              <span
                v-if="unitConvergence(u.run)"
                class="badge conv"
                :class="{ pass: unitConvergence(u.run) === 'converged', fail: unitConvergence(u.run) === 'failed' }"
                :title="unitConvergence(u.run) === 'unknown' ? 'The run did not converge; no message names this unit' : `In the recorded run: ${unitConvergence(u.run)}`"
                data-conv
              >{{ unitConvergence(u.run) }}</span>
            </td>
            <td class="spec">
              <ul v-if="specEntries(u.spec).length">
                <li v-for="e in specEntries(u.spec)" :key="e.key" :class="{ assumed: e.provenance === 'assumed' }" :data-spec="e.key">
                  <span class="key">{{ e.key.replace(/_/g, " ") }}</span>
                  {{ e.text }}
                  <span v-if="e.provenance" class="prov" :class="e.provenance" :title="[e.provenance, e.source].filter(Boolean).join(': ')">{{ PROVENANCE_SHORT[e.provenance] }}</span>
                  <span v-if="e.provenance === 'assumed' && e.source" class="muted source">{{ e.source }}</span>
                </li>
              </ul>
            </td>
            <td class="results">
              <div v-for="r in resultEntries(u.run?.results)" :key="r.key" :data-result="r.key">
                {{ r.label }} <span class="num">{{ r.text }}</span> {{ r.unit }}
              </div>
            </td>
            <td class="notes">
              <div v-if="u.reason" class="reason" data-reason>{{ u.reason }}</div>
              <div v-for="(w, i) in u.run?.warnings ?? []" :key="`w${i}`" class="warn" data-warning>{{ w }}</div>
              <div v-for="(m, i) in u.run?.messages ?? []" :key="`m${i}`" class="err">{{ m }}</div>
            </td>
          </tr>
          <tr v-if="!view.units.length">
            <td colspan="5" class="muted">No units.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <FindingsList :findings="findings" label="Simulation findings" />
  </section>
</template>

<style scoped>
h2 {
  font-size: var(--text-md, 15px);
  margin: var(--space-4) 0 var(--space-2);
}
.counts {
  font-weight: 400;
  font-size: var(--text-sm);
  margin-left: var(--space-1);
}
.facts {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: var(--space-1) var(--space-4);
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
}
.facts dt {
  color: var(--fg-muted);
}
.facts dd {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1) var(--space-2);
  min-width: 0;
  overflow-wrap: anywhere;
}
.file {
  font-size: 12px;
}
.hint {
  font-size: var(--text-sm);
  margin: 0 0 var(--space-2);
}
.notice p {
  margin: 0 0 var(--space-1);
}
.notice p:last-child {
  margin-bottom: 0;
}
.changed {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.units .id-cell {
  white-space: nowrap;
}
.units .type {
  display: block;
  font-size: 11.5px;
}
.units .status {
  white-space: nowrap;
}
.units .conv {
  margin-left: 4px;
}
.units ul {
  list-style: none;
  margin: 0;
  padding: 0;
}
.units .spec li {
  white-space: nowrap;
}
.units .spec .key {
  color: var(--fg-muted);
}
.units .spec li.assumed {
  white-space: normal;
}
.units .source {
  display: block;
  font-size: 11px;
  margin-left: var(--space-3);
  white-space: normal;
}
.units .results {
  white-space: nowrap;
}
.units .num {
  font-variant-numeric: tabular-nums;
}
.units .notes {
  min-width: 160px;
}
.reason {
  color: var(--fg-muted);
}
.warn {
  color: var(--warn);
}
.err {
  color: var(--bad);
}
@media (max-width: 700px) {
  .facts {
    grid-template-columns: minmax(0, 1fr);
    gap: 0;
  }
  .facts dd {
    margin-bottom: var(--space-2);
  }
}
</style>
