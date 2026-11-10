<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, ApiError, type SimulationView, type StreamTable } from "@/api";
import LoadState from "@/components/LoadState.vue";
import ProcessValueCell from "@/components/ProcessValueCell.vue";
import SimulationPanel from "@/components/SimulationPanel.vue";
import { store } from "@/store";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { refocusAfterLoad } from "@/lib/refocus";
import { shortRev } from "@/lib/format";
import {
  BALANCE_BADGE,
  PROVENANCE_SHORT,
  balanceDetail,
  bfdConnectionOf,
  filterStreams,
  compactComposition,
  formatComposition,
  formatPhase,
  streamStatus,
  type StreamFilter,
} from "@/lib/process";
import { filledFields, runTime } from "@/lib/simulation";

const route = useRoute();
const router = useRouter();
const { rev } = useRev();
const caseId = computed(() => (typeof route.query.case === "string" ? route.query.case : ""));
const table = useAsync((signal) => api.streams({ case: caseId.value, rev: rev.value }, signal), [caseId, rev]);
/**
 * The cases of the table shown: the case select stays (and keeps the focus) while another case
 * loads. Another revision may have other cases or none, and a table that failed has none.
 */
const cases = ref<StreamTable["cases"]>([]);
watch(
  () => table.data.value,
  (data) => {
    if (data) cases.value = data.cases;
  },
);
watch(rev, () => (cases.value = []));
watch(
  () => table.error.value,
  (error) => {
    if (error) cases.value = [];
  },
);

/** The simulation at `rev` for the case, or null without `process/simulation.yaml` (a 404, also an older server or a snapshot without it). */
const simulation = useAsync<SimulationView | null>(async (signal) => {
  try {
    return await api.simulation({ case: caseId.value, rev: rev.value }, signal);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}, [caseId, rev]);
const sim = computed(() => simulation.data.value ?? null);
const simMissing = computed(() => !simulation.loading.value && !simulation.error.value && simulation.data.value === null);

type Tab = "streams" | "simulation";
const tab = computed<Tab>(() => (route.query.tab === "simulation" ? "simulation" : "streams"));
const showTabs = computed(() => Boolean(sim.value) || tab.value === "simulation" || (simulation.loading.value && Boolean(store.repo?.has_simulation)));
function setTab(next: Tab): void {
  void router.replace({ query: { ...route.query, tab: next === "simulation" ? "simulation" : undefined } });
}
/** Stream id -> the fields the recorded run filled, for the table's case. */
const filled = computed(() => filledFields(sim.value, table.data.value?.case));
const simTitle = computed(() => {
  const run = sim.value?.run;
  if (!run) return "";
  const what = `${run.simulator.name}${run.simulator.version ? ` ${run.simulator.version}` : ""}, ${run.property_package}`;
  return `Filled by the simulation run of ${runTime(run.run_at)} (${what})${sim.value?.stale ? "; the run is stale: the inputs changed since" : ""}`;
});
const isFilled = (id: string, field: string) => filled.value.get(id)?.has(field) ?? false;

const text = ref(typeof route.query.q === "string" ? route.query.q : "");
const which = ref<StreamFilter>("all");
const selected = ref<string | null>(typeof route.query.stream === "string" ? route.query.stream : null);

/** Select a row, or unselect it when it is the selected one (click, Enter or Space). */
const toggle = (id: string) => (selected.value = selected.value === id ? null : id);

const streams = computed(() => filterStreams(table.data.value?.streams ?? [], text.value, which.value));
const balances = computed(() => table.data.value?.balances ?? []);
const wastewater = computed(() => table.data.value?.wastewater);
const problems = computed(() => balances.value.filter((b) => b.status === "imbalance").length);
const stale = computed(() => (table.data.value?.streams ?? []).filter((s) => s.stale.length).length);

/** `yes`, `internal`, or `in S2` for a stream drawn in another (aggregated) BFD connection. */
function bfdCell(id: string, onBfd: boolean): string {
  if (!onBfd) return "internal";
  const conn = table.data.value ? bfdConnectionOf(table.data.value, id) : undefined;
  return conn && conn !== id ? `in ${conn}` : "yes";
}

function setCase(id: string): void {
  void router.replace({ query: { ...route.query, case: id || undefined } });
}
// The simulation panel (and its case select) is redrawn once the picked case has loaded.
const keepSimCaseFocus = refocusAfterLoad('select[aria-label="Simulation case"]', simulation, rev);
function setSimCase(id: string): void {
  keepSimCaseFocus();
  setCase(id);
}

// A link to ?stream=S4 (the BFD/PFD panel) scrolls that row into view once the table is drawn.
watch(
  () => table.data.value,
  async (data) => {
    if (!data || !selected.value) return;
    await nextTick();
    document.querySelector(`tr[data-stream="${CSS.escape(selected.value)}"]`)?.scrollIntoView?.({ block: "center" });
  },
);
// A composition shows its largest fractions (#67): the whole list on a selected row, or for all rows.
const fullComposition = ref(false);
</script>

<template>
  <div class="page streams">
    <h1 v-if="tab === 'simulation'">
      Simulation
      <small>process/simulation.yaml{{ rev ? ` at ${shortRev(rev)}` : " in the working tree" }}</small>
      <span v-if="sim?.stale" class="badge warning">stale</span>
    </h1>
    <h1 v-else>
      Stream table
      <small>{{ shortRev(rev) }}</small>
      <span v-if="problems" class="badge fail">{{ problems }} balance error{{ problems > 1 ? "s" : "" }}</span>
      <span v-if="stale" class="badge warning">{{ stale }} stale</span>
    </h1>
    <div v-if="showTabs" class="tabs" role="tablist" aria-label="Process">
      <button type="button" role="tab" class="tab" :class="{ active: tab === 'streams' }" :aria-selected="tab === 'streams'" data-tab="streams" @click="setTab('streams')">Streams</button>
      <button type="button" role="tab" class="tab" :class="{ active: tab === 'simulation' }" :aria-selected="tab === 'simulation'" data-tab="simulation" @click="setTab('simulation')">Simulation</button>
    </div>

    <template v-if="tab === 'simulation'">
      <LoadState :loading="simulation.loading.value && !sim" :error="simulation.error.value" @retry="simulation.reload" />
      <div v-if="simMissing" class="notice" data-sim-missing>
        <p><strong>No simulation{{ rev ? ` at ${shortRev(rev)}` : "" }}.</strong></p>
        <p class="muted">
          <code>process/simulation.yaml</code> says what the simulator needs beyond the flowsheet (property package, unit specs); <code>cheme process simulate --fill</code> runs it
          and records the run. This server or snapshot has none to show.
        </p>
      </div>
      <SimulationPanel v-if="sim" :view="sim" @set-case="setSimCase" />
    </template>

    <template v-else>
    <div class="toolbar">
      <label v-if="cases.length" class="field">
        Case
        <select :value="table.data.value?.case ?? caseId" aria-label="Case" @change="setCase(($event.target as HTMLSelectElement).value)">
          <option v-for="c in cases" :key="c.id" :value="c.id">{{ c.id }}{{ c.description ? ` — ${c.description}` : "" }}</option>
        </select>
      </label>
      <input v-model="text" type="search" placeholder="Filter streams" aria-label="Filter streams" />
      <div class="seg" role="group" aria-label="Show">
        <button v-for="w in ['all', 'bfd', 'problems'] as const" :key="w" type="button" class="btn" :class="{ active: which === w }" @click="which = w">
          {{ w === "all" ? "All" : w === "bfd" ? "On BFD" : "Problems" }}
        </button>
      </div>
      <label class="check"><input v-model="fullComposition" type="checkbox" data-action="full-composition" /> full composition</label>
      <span class="spacer" />
      <span class="legend muted">
        <span class="prov given">G</span> given <span class="prov assumed">A</span> assumed
        <span class="prov calculated">C</span> calculated
        <template v-if="filled.size"><span class="sim-mark" :class="{ stale: sim?.stale }">sim</span> filled by the simulation</template>
      </span>
    </div>

    <LoadState :loading="table.loading.value && !table.data.value" :error="table.error.value" @retry="table.reload" />

    <template v-if="table.data.value">
      <div v-if="wastewater" class="notice wastewater-notice" data-wastewater>
        <p><strong>Wastewater results · saved final simulated time</strong>
          <span class="badge info">{{ wastewater.status }}</span>
          <span v-if="wastewater.stale === true" class="badge warning" data-wastewater-stale>stale: inputs changed</span>
          <span v-else-if="wastewater.stale === null" class="badge warning">input match not established</span>
        </p>
        <p v-if="wastewater.run_at || wastewater.evidence" class="muted">
          {{ wastewater.run_at ? runTime(wastewater.run_at) : '' }} · {{ wastewater.evidence }}
        </p>
        <p class="muted">
          Flow is liquid volume per day; concentrations retain COD, N, P and TSS measurement bases.
          These are calculated values, not measured plant data or proof of steady state or elemental conservation.
          <RouterLink :to="{ path: '/file/' + wastewater.run_file, query: rev ? { rev } : {} }">Saved run record</RouterLink>
        </p>
        <p v-if="wastewater.stale" class="muted">Changed inputs: {{ wastewater.changed_files.join(', ') || 'fingerprint differs' }}. Values below belong to the earlier run.</p>
        <details v-if="wastewater.findings.length" data-wastewater-findings>
          <summary>{{ wastewater.findings.length }} record issue(s) · missing values are shown as —</summary>
          <ul><li v-for="(f, i) in wastewater.findings" :key="i">{{ f.message }} {{ f.hint }}</li></ul>
        </details>
      </div>
      <p class="muted count">
        {{ streams.length }} of {{ table.data.value.streams.length }} streams
        <template v-if="wastewater"> · units shown in column headings · C = calculated · — = no usable recorded value</template>
        <template v-else> · units: pressure {{ table.data.value.units.pressure }},
        temperature {{ table.data.value.units.temperature }}, flow {{ table.data.value.units.flow }}, duty {{ table.data.value.units.duty }}
        </template>
      </p>
      <div class="table-wrap">
        <table class="data stream-table">
          <thead>
            <tr>
              <th>Stream</th>
              <th>From → to</th>
              <th>BFD</th>
              <template v-if="wastewater">
                <th v-for="column in wastewater.columns" :key="column.key" :title="column.basis" :data-wastewater-column="column.key">
                  {{ column.label }}<div class="muted small">{{ column.unit }}</div>
                </th>
              </template>
              <template v-else>
              <th>Pressure</th>
              <th>Temperature</th>
              <th>Flow</th>
              <th>Duty</th>
              <th>Composition</th>
              <th>Phase</th>
              <th>Calculated</th>
              </template>
              <th>Links</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="s in streams"
              :key="s.id"
              :data-stream="s.id"
              class="clickable"
              :class="[streamStatus(s), { selected: selected === s.id }]"
              tabindex="0"
              :aria-current="selected === s.id || undefined"
              @click="toggle(s.id)"
              @keydown.enter.self="toggle(s.id)"
              @keydown.space.self.prevent="toggle(s.id)"
            >
              <td class="stream">
                <strong>{{ s.id }}</strong> <span class="muted">{{ s.title }}</span>
                <span v-if="s.kind !== 'material'" class="badge info">{{ s.kind }}</span>
                <div v-if="s.imbalance.length" class="err">balance: {{ s.imbalance.join(", ") }}</div>
              </td>
              <td class="mono">{{ s.from }} → {{ s.to }}</td>
              <td class="bfd">{{ bfdCell(s.id, s.on_bfd) }}</td>
              <template v-if="wastewater">
                <td v-for="column in wastewater.columns" :key="column.key" class="num" :data-field="column.key">
                  <ProcessValueCell v-if="s.wastewater?.[column.key]" :value="s.wastewater[column.key]" :show-unit="false" />
                  <span v-else class="muted" title="No usable recorded value">—</span>
                </td>
              </template>
              <template v-else>
              <td class="num" :data-field="'pressure'"><ProcessValueCell :value="s.properties.pressure" /><span v-if="isFilled(s.id, 'pressure')" class="sim-mark" :class="{ stale: sim?.stale }" :title="simTitle" data-sim>sim</span></td>
              <td class="num" :data-field="'temperature'"><ProcessValueCell :value="s.properties.temperature" /><span v-if="isFilled(s.id, 'temperature')" class="sim-mark" :class="{ stale: sim?.stale }" :title="simTitle" data-sim>sim</span></td>
              <td class="num" :data-field="'flow'"><ProcessValueCell :value="s.properties.flow" /><span v-if="isFilled(s.id, 'flow')" class="sim-mark" :class="{ stale: sim?.stale }" :title="simTitle" data-sim>sim</span></td>
              <td class="num" :data-field="'duty'"><ProcessValueCell :value="s.properties.duty" /><span v-if="isFilled(s.id, 'duty')" class="sim-mark" :class="{ stale: sim?.stale }" :title="simTitle" data-sim>sim</span></td>
              <td class="composition">
                <template v-if="s.composition">
                  <template v-if="fullComposition || selected === s.id || !compactComposition(s)?.more">{{ formatComposition(s) }}</template>
                  <span v-else :title="formatComposition(s)" data-composition="compact"
                    >{{ compactComposition(s)!.text }} <span class="muted">+{{ compactComposition(s)!.more }} more</span></span
                  >
                  <span class="prov" :class="s.composition.provenance">{{ PROVENANCE_SHORT[s.composition.provenance] }}</span>
                  <span v-if="isFilled(s.id, 'composition')" class="sim-mark" :class="{ stale: sim?.stale }" :title="simTitle" data-sim>sim</span>
                </template>
              </td>
              <td>
                <template v-if="s.phase">
                  {{ formatPhase(s) }} <span class="prov" :class="s.phase.provenance">{{ PROVENANCE_SHORT[s.phase.provenance] }}</span>
                  <span v-if="s.phase.stale" class="badge warning">stale</span>
                </template>
              </td>
              <td>
                <div v-for="(v, name) in s.calculated" :key="name">{{ name }} <ProcessValueCell :value="v" /></div>
              </td>
              </template>
              <td>
                <span v-for="l in s.links" :key="l.target + l.ref" class="badge" :class="l.resolved ? 'pass' : 'info'" :title="l.problem ?? 'resolved'">
                  {{ l.target }} {{ l.ref }}
                </span>
              </td>
            </tr>
            <tr v-if="!streams.length">
              <td :colspan="wastewater ? 4 + wastewater.columns.length : 11" class="muted">No streams.</td>
            </tr>
          </tbody>
        </table>
      </div>

      <component :is="wastewater ? 'details' : 'div'" class="balance-section">
      <summary v-if="wastewater">Molecular mass-balance checks (separate from wastewater results)</summary>
      <p v-if="wastewater" class="muted">The existing checks require molecular mass flows in kg/h. Wastewater values above do not populate those fields, so these checks may remain not-evaluable. COD/N/P conservation requires a separate balance including reactions, accumulation, sludge and gas.</p>
      <h2>Balances <span class="muted small">(steady state, non-reactive, boundary streams; tolerance per block)</span></h2>
      <div class="table-wrap">
        <table class="data balance-table">
          <thead>
            <tr>
              <th>Block / step</th>
              <th>Status</th>
              <th>In</th>
              <th>Out</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="b in balances" :key="b.node" :data-balance="b.node" :class="{ error: b.status === 'imbalance' }">
              <td><strong>{{ b.node }}</strong> <span class="muted">{{ b.title }}</span> <span class="faint">{{ b.kind }}</span></td>
              <td><span class="badge" :class="BALANCE_BADGE[b.status]">{{ b.status }}</span></td>
              <td class="mono small">{{ b.streams_in.join(", ") }}</td>
              <td class="mono small">{{ b.streams_out.join(", ") }}</td>
              <td>{{ balanceDetail(b) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      </component>
    </template>
    </template>
  </div>
</template>

<style scoped>
.tabs {
  display: inline-flex;
  gap: 2px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 2px;
  margin-bottom: var(--space-2);
}
.tab {
  background: none;
  border: none;
  border-radius: calc(var(--radius) - 2px);
  padding: 2px 14px;
  font: inherit;
  font-weight: 600;
  color: var(--fg-muted);
  cursor: pointer;
}
.tab.active {
  background: var(--accent-soft);
  color: var(--accent);
}
.sim-mark {
  margin-left: 3px;
}
h2 {
  font-size: var(--text-md, 15px);
  margin: var(--space-4) 0 var(--space-2);
}
.field {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-sm);
}
.seg {
  display: inline-flex;
  gap: 2px;
}
.count {
  margin: 0 0 var(--space-2);
  font-size: var(--text-sm);
}
.wastewater-notice { margin-bottom: var(--space-3); }
.balance-section { margin-top: var(--space-3); }
.balance-section summary { cursor: pointer; }
.legend {
  font-size: var(--text-sm);
}
.table-wrap {
  max-height: calc(100vh - 330px);
}
.balance-table {
  max-height: none;
}
td.num {
  text-align: right;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.mono {
  font-family: var(--mono);
  font-size: 12px;
}
.small {
  font-size: var(--text-sm);
}
tr.error td {
  background: var(--bad-soft);
}
tr.stale td {
  background: var(--warn-soft);
}
.err {
  color: var(--bad);
  font-size: 12px;
}
.check {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-sm);
}
/* wide enough that a row stays two or three lines (#67); the table scrolls sideways */
.stream-table td.stream {
  min-width: 200px;
}
.stream-table td.composition {
  min-width: 280px;
}
</style>
