<script setup lang="ts">
import SectionBar from "@/components/SectionBar.vue";
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, ApiError, type EquipmentEstimate, type EstimateLine, type Finding, type MtoReport, type MtoRow } from "@/api";
import EquipmentEstimatePanel from "@/components/EquipmentEstimatePanel.vue";
import LoadState from "@/components/LoadState.vue";
import { datasheetPaths } from "@/lib/studies";
import { store } from "@/store";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { useInPageLink } from "@/lib/inPageLink";
import { pathSegments, shortRev } from "@/lib/format";
import { dnText, estimateCsv, groupRows, money, mtoCsv, quantity, rowMatches } from "@/lib/mto";

const { rev, withRev } = useRev();

/** The take-off at `rev`, or null when there is no committed model there (a 404). */
const report = useAsync<MtoReport | null>(async (signal) => {
  try {
    return await api.mto(rev.value, signal);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}, rev);
const data = computed(() => report.data.value ?? null);
const missing = computed(() => !report.loading.value && !report.error.value && report.data.value === null);

/** The equipment estimate at `rev`, or null when there is nothing to estimate (a 404, also an older server or a snapshot without it). */
const equipment = useAsync<EquipmentEstimate | null>(async (signal) => {
  try {
    return await api.equipmentEstimate(rev.value, signal);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}, rev);
const equipmentData = computed(() => equipment.data.value ?? null);
const equipmentMissing = computed(() => !equipment.loading.value && !equipment.error.value && equipment.data.value === null);
/** Datasheet links of the equipment lines (the tree as committed at `rev`; none when it fails). */
const tree = useAsync((signal) => api.tree(rev.value, signal).catch(() => []), rev);
const datasheets = computed(() => datasheetPaths(tree.data.value ?? []));

const route = useRoute();
const router = useRouter();
type Tab = "takeoff" | "equipment";
/** The tab shown: `?tab=equipment`, else the take-off, unless there is no model but an equipment estimate. */
const tab = computed<Tab>(() => {
  if (route.query.tab === "equipment") return "equipment";
  if (route.query.tab === "takeoff") return "takeoff";
  return missing.value && equipmentData.value ? "equipment" : "takeoff";
});
const showTabs = computed(() => Boolean(equipmentData.value) || route.query.tab === "equipment" || (equipment.loading.value && Boolean(store.repo?.has_equipment_estimate)));
function setTab(next: Tab): void {
  void router.replace({ query: { ...route.query, tab: next === "takeoff" ? "takeoff" : "equipment" } });
}

const query = ref("");
/** The total cards link to their category's section (in a snapshot too, where the hash is the route). */
const inPage = useInPageLink();
const groups = computed(() => groupRows(data.value?.rows ?? []));
const shown = computed(() =>
  groups.value.map((g) => ({ ...g, rows: g.rows.filter((r) => rowMatches(r, query.value)) })).filter((g) => g.rows.length || !query.value),
);
const estimate = computed(() => data.value?.estimate ?? null);
const currency = computed(() => (estimate.value?.currency && estimate.value.currency !== "XXX" ? estimate.value.currency : ""));
/** The priced line of each take-off row (by the row's key). */
const priced = computed(() => new Map((estimate.value?.lines ?? []).filter((l) => l.section === "material").map((l) => [l.id, l])));
const factors = computed<EstimateLine[]>(() => (estimate.value?.lines ?? []).filter((l) => l.section !== "material"));
/** Material cost per category. */
const categoryCost = computed(() => {
  const out = new Map<string, number>();
  for (const g of groups.value) {
    let sum = 0;
    for (const r of g.rows) sum += priced.value.get(r.key)?.cost ?? 0;
    out.set(g.category, Math.round(sum * 100) / 100);
  }
  return out;
});
const findings = computed<Finding[]>(() => [...(data.value?.findings ?? []), ...(estimate.value?.findings ?? [])]);
const hasLength = (rows: { length_m: number | null }[]) => rows.some((r) => r.length_m !== null);
/** The text columns a category fills (steel has no DN or class, pipe no group). */
const usedColumns = (rows: MtoRow[]) => ({ dn: rows.some((r) => r.dn !== null), class: rows.some((r) => r.class), spec: rows.some((r) => r.spec), group: rows.some((r) => r.group) });
const totalText = (totals: Record<string, number>) =>
  Object.entries(totals)
    .map(([unit, v]) => `${quantity(v)} ${unit}`)
    .join(", ");

function download(name: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
const suffix = computed(() => (rev.value ? `-${shortRev(rev.value)}` : ""));
function downloadMto(): void {
  if (data.value) download(`mto${suffix.value}.csv`, mtoCsv(data.value.rows));
}
function downloadEstimate(): void {
  if (estimate.value) download(`estimate${suffix.value}.csv`, estimateCsv(estimate.value.lines));
}
const SECTION_TITLES: Record<string, string> = { direct: "direct", indirect: "indirect", contingency: "contingency" };
</script>

<template>
  <div class="page mto">
    <div class="heading">
      <h1 v-if="tab === 'equipment'">
        Equipment estimate
        <small>equipment list and estimate/cost-basis.yaml{{ rev ? ` at ${shortRev(rev)}` : " in the working tree" }}</small>
      </h1>
      <h1 v-else>
        Material take-off
        <small>{{ data?.model ?? "layout/plant-model.yaml" }}{{ rev ? ` at ${shortRev(rev)}` : " in the working tree" }}</small>
      </h1>
      <div v-if="showTabs" class="tabs" role="tablist" aria-label="Estimate">
        <button type="button" role="tab" class="tab" :class="{ active: tab === 'takeoff' }" :aria-selected="tab === 'takeoff'" data-tab="takeoff" @click="setTab('takeoff')">Take-off</button>
        <button type="button" role="tab" class="tab" :class="{ active: tab === 'equipment' }" :aria-selected="tab === 'equipment'" data-tab="equipment" @click="setTab('equipment')">Equipment</button>
      </div>
    </div>

    <template v-if="tab === 'equipment'">
      <LoadState :loading="equipment.loading.value && !equipmentData" :error="equipment.error.value" @retry="equipment.reload" />
      <div v-if="equipmentMissing" class="notice" data-equipment-missing>
        <p><strong>No equipment estimate{{ rev ? ` at ${shortRev(rev)}` : "" }}.</strong></p>
        <p class="muted">
          It costs the items of the equipment list (<code>cheme assess equipment</code>, with <code>estimate/cost-basis.yaml</code> for the cost index and
          the project's own costs); this server or snapshot has none to show.
        </p>
      </div>
      <EquipmentEstimatePanel v-if="equipmentData" :estimate="equipmentData" :datasheets="datasheets" :has-layout="Boolean(store.repo?.has_layout)" />
    </template>

    <LoadState v-if="tab === 'takeoff'" :loading="report.loading.value && !data" :error="report.error.value" @retry="report.reload" />
    <div v-if="tab === 'takeoff' && missing" class="notice">
      <p><strong>No 3D model{{ rev ? ` at ${shortRev(rev)}` : "" }}.</strong></p>
      <p class="muted">The take-off counts the committed <code>layout/plant-model.yaml</code>: run <code>cheme layout build</code> and commit it.</p>
      <p v-if="equipmentData" class="muted">The equipment estimate needs no model: see the <button type="button" class="link" @click="setTab('equipment')">Equipment</button> tab.</p>
      <p v-else-if="equipmentMissing" class="muted">An equipment estimate from the equipment list: <code>cheme assess equipment</code>.</p>
    </div>

    <template v-if="tab === 'takeoff' && data">
      <SectionBar />
      <div class="toolbar">
        <input v-model="query" class="filter" type="search" placeholder="Filter: DN100, PN16, HEB300, cold…" aria-label="Filter the rows" />
        <span class="spacer" />
        <button type="button" class="btn" data-action="mto-csv" title="The take-off as cheme assess mto --csv writes it (estimate/mto.csv)" @click="downloadMto">Take-off CSV</button>
        <button v-if="estimate?.lines.length" type="button" class="btn" data-action="estimate-csv" title="The estimate as cheme assess estimate --csv writes it (estimate/estimate.csv)" @click="downloadEstimate">
          Estimate CSV
        </button>
      </div>
      <p class="muted hint">
        Counted from the model's pipes and parts (<code>cheme assess mto</code>); model
        <code>{{ data.model_sha256?.slice(0, 12) ?? "?" }}</code>, {{ data.rows.length }} rows. Bulk materials only: no equipment, no
        olets, spool flanges or field-run small bore.
      </p>

      <section class="cards" aria-label="Totals">
        <a v-for="g in groups" :key="g.category" class="card" :href="inPage.href(`mto-${g.category}`)" :data-category="g.category" @click="inPage.go($event, `mto-${g.category}`)">
          <span class="card-title">{{ g.title }}</span>
          <strong class="card-value">{{ totalText(g.totals) }}</strong>
          <span class="muted">{{ g.rows.length }} {{ g.rows.length === 1 ? "row" : "rows" }}<template v-if="estimate && categoryCost.get(g.category)"> · {{ money(categoryCost.get(g.category), currency) }}</template></span>
        </a>
      </section>

      <section v-if="estimate" class="estimate" aria-label="Estimate">
        <h2>
          Estimate
          <span class="muted">{{ estimate.currency === "XXX" ? "no currency" : estimate.currency }}<template v-if="estimate.cost_year">, {{ estimate.cost_year }}</template></span>
          <span v-if="estimate.example" class="badge warning">example rates</span>
        </h2>
        <p v-if="estimate.example" class="notice warning" role="note">
          The rates are an example (<code>example: true</code> in <code>estimate/rates.yaml</code>): these numbers price nothing real. Rates, factors
          and contingency are a cost engineer's decision.
        </p>
        <dl v-if="estimate.totals.total !== undefined" class="totals">
          <dt>materials</dt>
          <dd>{{ money(estimate.totals.materials, currency) }}</dd>
          <dt>direct</dt>
          <dd>{{ money(estimate.totals.direct, currency) }}</dd>
          <dt>indirect</dt>
          <dd>{{ money(estimate.totals.indirect, currency) }}</dd>
          <dt>contingency</dt>
          <dd>{{ money(estimate.totals.contingency, currency) }}</dd>
          <dt class="total">total</dt>
          <dd class="total" data-total>{{ money(estimate.totals.total, currency) }}</dd>
          <template v-if="estimate.totals.unpriced_rows">
            <dt>unpriced rows</dt>
            <dd class="bad">{{ estimate.totals.unpriced_rows }}</dd>
          </template>
        </dl>
        <div v-if="factors.length" class="table-wrap">
          <table class="data factors" aria-label="Factors">
            <thead>
              <tr><th>section</th><th>factor</th><th>on</th><th class="num">rate</th><th class="num">cost</th><th>source</th></tr>
            </thead>
            <tbody>
              <tr v-for="f in factors" :key="f.section + f.id">
                <td>{{ SECTION_TITLES[f.section] ?? f.section }}</td>
                <td>{{ f.description }} <code class="muted">{{ f.id }}</code></td>
                <td class="num">{{ money(f.quantity, currency) }}</td>
                <td class="num">{{ f.rate ?? "" }}</td>
                <td class="num">{{ money(f.cost, currency) }}</td>
                <td class="muted">{{ f.status }}, {{ f.source }}<template v-if="f.year">, {{ f.year }}</template></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="findings.length" class="findings" aria-label="Findings">
        <h2>Findings</h2>
        <ul>
          <li v-for="(f, i) in findings" :key="i">
            <span class="badge" :class="f.level">{{ f.level }}</span>
            <code class="rule">{{ f.rule.replace(/^cheme\./, "") }}</code>
            {{ f.message }}
            <RouterLink class="file" :to="{ name: 'file', params: { path: pathSegments(f.file) }, query: withRev(f.line ? { line: String(f.line) } : {}) }">{{ f.file }}</RouterLink>
          </li>
        </ul>
      </section>

      <p v-if="query && !shown.length" class="muted">No row matches "{{ query }}".</p>
      <section v-for="g in shown" :id="`mto-${g.category}`" :key="g.category" class="category" :data-category="g.category">
        <template v-for="cols in [usedColumns(g.rows)]" :key="'c'">
        <h2>
          {{ g.title }}
          <span class="muted">{{ totalText(g.totals) }}</span>
        </h2>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr>
                <th>item</th>
                <th v-if="cols.dn">DN</th>
                <th v-if="cols.class">class</th>
                <th v-if="cols.spec">spec</th>
                <th v-if="cols.group">group</th>
                <th class="num">count</th>
                <th class="num">quantity</th>
                <th>unit</th>
                <th v-if="hasLength(g.rows)" class="num">length, m</th>
                <template v-if="estimate">
                  <th class="num">rate</th>
                  <th class="num">cost</th>
                </template>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in g.rows" :key="r.key" :data-key="r.key">
                <td>{{ r.item }}</td>
                <td v-if="cols.dn" class="nowrap">{{ dnText(r) }}</td>
                <td v-if="cols.class">{{ r.class }}</td>
                <td v-if="cols.spec">{{ r.spec }}</td>
                <td v-if="cols.group">{{ r.group }}</td>
                <td class="num">{{ r.count }}</td>
                <td class="num">{{ quantity(r.quantity) }}</td>
                <td>{{ r.unit }}</td>
                <td v-if="hasLength(g.rows)" class="num">{{ quantity(r.length_m) }}</td>
                <template v-if="estimate">
                  <td class="num" :title="priced.get(r.key)?.basis">{{ priced.get(r.key)?.rate ?? "" }}</td>
                  <td class="num" :class="{ bad: !priced.get(r.key) || priced.get(r.key)?.cost === null }">{{ priced.get(r.key)?.cost != null ? money(priced.get(r.key)?.cost) : "unpriced" }}</td>
                </template>
              </tr>
            </tbody>
          </table>
        </div>
        </template>
      </section>
    </template>
  </div>
</template>

<style scoped>
.heading {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--space-2) var(--space-4);
}
.heading h1 {
  margin-right: auto;
}
.tabs {
  display: flex;
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
.link {
  background: none;
  border: none;
  padding: 0;
  font: inherit;
  color: var(--accent);
  cursor: pointer;
}
.hint {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
}
.filter {
  min-width: 260px;
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--fg);
  font: inherit;
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}
.card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--fg);
  font-size: var(--text-sm);
}
.card:hover {
  border-color: var(--accent);
  text-decoration: none;
}
.card-title {
  color: var(--fg-muted);
}
.card-value {
  font-size: var(--text-lg);
  font-variant-numeric: tabular-nums;
}
h2 {
  font-size: var(--text);
  margin: var(--space-4) 0 var(--space-2);
  display: flex;
  gap: var(--space-2);
  align-items: baseline;
  flex-wrap: wrap;
}
h2 .muted {
  font-weight: normal;
  font-size: var(--text-sm);
}
.estimate .notice {
  margin: 0 0 var(--space-2);
}
.totals {
  display: grid;
  grid-template-columns: max-content max-content;
  gap: 2px var(--space-4);
  margin: 0 0 var(--space-3);
  font-variant-numeric: tabular-nums;
}
.totals dt {
  color: var(--fg-muted);
}
.totals dd {
  margin: 0;
  text-align: right;
}
.totals .total {
  font-weight: 600;
  color: var(--fg);
  border-top: 1px solid var(--border);
  padding-top: 2px;
}
.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.nowrap {
  white-space: nowrap;
}
.bad {
  color: var(--bad);
}
.findings ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  font-size: var(--text-sm);
}
.findings .rule {
  margin: 0 var(--space-1);
}
.findings .file {
  margin-left: var(--space-2);
  font-size: var(--text-sm);
}
.category table td {
  font-size: var(--text-sm);
}
</style>
