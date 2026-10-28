<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { api, ApiError, type Branch, type Commit, type Finding, type LcaReport } from "@/api";
import LciReadiness from "@/components/LciReadiness.vue";
import LoadState from "@/components/LoadState.vue";
import SankeyChart from "@/components/SankeyChart.vue";
import ScenarioBars from "@/components/ScenarioBars.vue";
import UncertaintyRange from "@/components/UncertaintyRange.vue";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { pathSegments, shortRev } from "@/lib/format";
import { quantity } from "@/lib/mto";
import {
  droppedIn,
  hasTotal,
  gapsOf,
  gapText,
  allocationRows,
  BASELINE,
  compareContributions,
  compareTotals,
  contributionSankey,
  contributions,
  impactsOf,
  impactText,
  labelOf,
  lcaCsv,
  scenarioBars,
  scenarioIds,
  verdictOf,
  sensitivityLabel,
  shareText,
  sourceHref,
  statisticsOf,
  statusClass,
  total,
} from "@/lib/lca";

const { rev, withRev } = useRev();

/** The LCA at `rev`, or null when there is no `lca/lca.yaml` there (a 404). */
const report = useAsync<LcaReport | null>(async (signal) => {
  try {
    return await api.lca(rev.value, signal);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}, rev);
const data = computed(() => report.data.value ?? null);
const missing = computed(() => !report.loading.value && !report.error.value && report.data.value === null);

const category = ref("");
const scenario = ref(BASELINE);
watch(data, (d) => {
  if (!d) return;
  if (!d.categories.some((c) => c.id === category.value)) category.value = d.categories[0]?.id ?? "";
  if (!scenarioIds(d).includes(scenario.value)) scenario.value = BASELINE;
});
const categoryInfo = computed(() => data.value?.categories.find((c) => c.id === category.value) ?? null);
const unit = computed(() => categoryInfo.value?.unit ?? "");
const scenarios = computed(() => (data.value ? scenarioIds(data.value) : []));

const parts = computed(() => (data.value && category.value ? contributions(data.value, scenario.value, category.value) : []));
/** The Sankey is as tall as its contributors' labels need. */
const sankey = computed(() =>
  data.value && category.value ? contributionSankey(data.value, scenario.value, category.value, { width: 520, height: Math.max(240, parts.value.length * 40 + 120), nodeWidth: 12, gap: 6, slot: 30 }) : null,
);
const bars = computed(() => (data.value && category.value ? scenarioBars(data.value, category.value) : null));
// data the baseline has that this scenario lacks (pre-release issue 172): its total is no lower footprint
const dropped = computed(() => (data.value && category.value ? droppedIn(data.value, scenario.value, category.value) : []));
const verdict = computed(() => (data.value ? verdictOf(data.value, scenario.value, category.value || undefined) : undefined));
const details = computed(() => data.value?.scenario_details ?? []);
// no total to show or to take shares of: never a zero or a lower footprint
const standing = computed(() => (data.value && category.value ? hasTotal(data.value, scenario.value, category.value) : true));
const ELECTRICITY: Record<string, string> = {
  "grid-average": "grid average",
  "residual-mix": "residual mix",
  contractual: "contractual supply",
  "on-site": "on-site generation",
};
/** The baseline's contributors first (shared with the bars), then any only this scenario names. */
const colourKeys = computed(() => {
  const keys = [...(bars.value?.keys ?? [])];
  for (const c of parts.value) if (!keys.includes(c.key)) keys.push(c.key);
  return keys;
});

const rows = computed(() => (data.value && category.value ? impactsOf(data.value, scenario.value, category.value).slice().sort((a, b) => Math.abs(b.value) - Math.abs(a.value)) : []));
const categoryTotal = computed(() => (data.value && category.value ? total(data.value, scenario.value, category.value) : 0));
const phaseTotals = computed(() => {
  const out = new Map<string, number>();
  for (const r of rows.value) out.set(r.phase, (out.get(r.phase) ?? 0) + r.value);
  return [...out.entries()];
});
const unmapped = computed(() => data.value?.inventory.filter((r) => !r.mapping).map((r) => r.key) ?? []);
const findings = computed<Finding[]>(() => data.value?.findings ?? []);
const gaps = computed(() => (data.value && category.value ? gapsOf(data.value, scenario.value, category.value) : []));
const outside = computed(() => (data.value && category.value ? gapsOf(data.value, scenario.value, category.value, true) : []));
// the card shows one category: its own gaps, not the scenario's
const withGaps = computed(() => gaps.value.length > 0);
const resultClass = computed(() => {
  const c = data.value?.classification;
  return c === "complete" ? "ok" : c === "unavailable" || c === "partial" ? "warning" : "info";
});
const shares = computed(() =>
  Object.entries(data.value?.allocation.shares ?? {})
    .map(([name, share]) => `${name} ${shareText(share)}`)
    .join(", "),
);

const allocation = computed(() => (data.value && category.value ? allocationRows(data.value, category.value) : []));
/** The Monte Carlo of the baseline in this category (shown for the baseline only). */
const stats = computed(() => (data.value && category.value ? statisticsOf(data.value, category.value) : null));

// -- another revision, for comparison ----------------------------------------------------------
const other = ref("");
const choices = useAsync<{ branches: Branch[]; commits: Commit[] }>(async (signal) => {
  const [branches, commits] = await Promise.all([api.branches(signal).catch(() => []), api.log({ limit: 20, path: "lca", rev: rev.value }, signal).catch(() => [])]);
  return { branches, commits };
}, rev);
const otherReport = useAsync<LcaReport | null>(async (signal) => {
  if (!other.value) return null;
  try {
    return await api.lca(other.value, signal);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}, other);
/** The other revision's LCA, only once it is the one asked for (not a previous one while loading). */
const otherData = computed(() => (other.value && !otherReport.loading.value ? (otherReport.data.value ?? null) : null));
const otherError = computed(() => (other.value && !otherReport.loading.value ? otherReport.error.value : null));
/** The functional unit's product, for the share column (any unit: "1 t GOXP", "1 MWh"). */
const product = computed(() => (data.value ? data.value.functional_unit.split(" ").slice(-1)[0] : ""));
const compared = computed(() => (data.value && otherData.value ? compareTotals(data.value, otherData.value) : []));
const changes = computed(() => (data.value && otherData.value && category.value ? compareContributions(data.value, otherData.value, category.value) : []));
const signed = (v: number) => (v > 0 ? "+" : "") + impactText(v);
/** The change relative to the other revision, e.g. `-12.5 %`. */
const percent = (delta: number, base: number) => `${delta > 0 ? "+" : ""}${((delta / Math.abs(base)) * 100).toFixed(1)} %`;

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
function downloadResults(): void {
  if (data.value) download(`lca-results${rev.value ? `-${shortRev(rev.value)}` : ""}.csv`, lcaCsv(data.value));
}
</script>

<template>
  <div class="page lca">
    <h1>
      Life cycle assessment
      <small>{{ data ? `per ${data.functional_unit}` : "lca/lca.yaml" }}{{ rev ? ` at ${shortRev(rev)}` : " in the working tree" }}</small>
    </h1>

    <LoadState :loading="report.loading.value && !data" :error="report.error.value" @retry="report.reload" />
    <div v-if="missing" class="notice">
      <p><strong>No LCA{{ rev ? ` at ${shortRev(rev)}` : "" }}.</strong></p>
      <p class="muted">The page shows <code>cheme assess lca</code>: write <code>lca/lca.yaml</code> (goal and scope, the background of each flow) and commit it. See the skill <code>lca</code>.</p>
    </div>

    <template v-if="data">
      <p v-if="data.example_factors" class="notice warning" role="note">
        The factors are an example (<code>example: true</code> in <code>lca/factors.yaml</code>): these numbers characterise nothing real.
      </p>
      <p v-if="data.label" class="notice result" :class="resultClass" role="note" data-result>
        <strong>{{ data.label }}</strong><span v-if="data.reasons?.length" class="muted">: {{ data.reasons.join("; ") }}</span>
      </p>
      <p v-if="data.publication?.publishable && data.publication.restricted_by.length" class="notice info" role="note" data-publication-decision>
        Published under the study's reviewed decision: the results draw on {{ data.publication.policy }} sources ({{ data.publication.restricted_by.join(", ") }}) whose terms permit it.
      </p>
      <p v-if="data.publication && !data.publication.publishable" class="notice warning" role="note" data-publication>
        Not for publication: the results draw on {{ data.publication.policy }} sources ({{ data.publication.restricted_by.join(", ") }}). Keep them private unless their terms and a reviewed decision allow more.
      </p>
      <dl class="meta">
        <dt>case</dt>
        <dd>{{ data.case }}</dd>
        <dt>boundary</dt>
        <dd>{{ data.boundary }}</dd>
        <dt>allocation</dt>
        <dd>{{ data.allocation.method }}<span class="muted"> ({{ shares }})</span></dd>
        <dt>background</dt>
        <dd>{{ data.background }}</dd>
      </dl>

      <div class="toolbar">
        <label v-if="data.categories.length > 1">
          Category
          <select v-model="category" data-action="category">
            <option v-for="c in data.categories" :key="c.id" :value="c.id">{{ c.title || c.id }}</option>
          </select>
        </label>
        <label v-if="scenarios.length > 1">
          Scenario
          <select v-model="scenario" data-action="scenario">
            <option v-for="s in scenarios" :key="s" :value="s">{{ s }}</option>
          </select>
        </label>
        <span class="spacer" />
        <button type="button" class="btn" data-action="lca-csv" title="The impacts as cheme assess lca --csv writes them (lca/results.csv)" @click="downloadResults">Results CSV</button>
      </div>

      <section class="cards" aria-label="Totals">
        <div class="card" data-card="total">
          <span class="card-title">{{ categoryInfo?.title || category }}, {{ scenario }}</span>
          <strong v-if="standing" class="card-value">{{ impactText(categoryTotal) }} <span class="unit">{{ unit }}</span></strong>
          <strong v-else class="card-value" data-no-total>no total</strong>
          <span class="muted">per {{ data.functional_unit }}</span>
          <span v-if="withGaps" class="muted" data-with-gaps>without its gaps (below), not counted as 0</span>
          <span v-if="dropped.length" class="warn-text" data-not-comparable>not comparable with the baseline: no background here for {{ dropped.map((k) => labelOf(data!, k)).join(", ") }}</span>
          <span v-if="verdict && verdict.kind !== 'baseline'" class="muted" :data-verdict="verdict.kind">
            <span class="badge" :class="verdict.badge">{{ verdict.label }}</span> {{ verdict.text }}
          </span>
          <span v-if="stats && scenario === BASELINE" class="muted" data-interval>95 %: {{ impactText(stats.low) }} .. {{ impactText(stats.high) }}</span>
        </div>
        <div v-for="[phase, value] in standing ? phaseTotals : []" :key="phase" class="card" :data-card="phase">
          <span class="card-title">{{ phase }}</span>
          <strong class="card-value">{{ impactText(value) }} <span class="unit">{{ unit }}</span></strong>
          <span class="muted">{{ categoryTotal ? shareText(value / categoryTotal) : "" }}</span>
        </div>
      </section>

      <section v-if="sankey && sankey.nodes.length" class="chart" aria-label="Contributions">
        <h2>
          Contributions
          <span class="muted">{{ categoryInfo?.method }}</span>
        </h2>
        <SankeyChart :layout="sankey" :keys="colourKeys" :unit="unit" :title="`Contributions to ${categoryInfo?.title || category} per ${data.functional_unit}, ${scenario}`" />
        <p class="muted hint">Each flow of the inventory into its phase, the phases into the functional unit; band widths are impacts. Hatched: a credit.</p>
      </section>
      <p v-else class="muted">No contribution in this category and scenario.</p>

      <section v-if="bars && scenarios.length > 1" class="chart" aria-label="Scenarios">
        <h2>Scenarios <span class="muted">{{ categoryInfo?.title || category }}, {{ unit }}</span></h2>
        <ScenarioBars :bars="bars" :unit="unit" :report="data" />
        <ul v-if="details.length" class="scenario-details muted" data-scenario-details>
          <li v-for="d in details" :key="d.id">
            <code>{{ d.id }}</code>{{ d.title ? `: ${d.title}` : "" }}
            <template v-if="d.location"> · background {{ d.location }}{{ d.year ? ` ${d.year}` : "" }} (not a plant location)</template>
            <template v-if="d.electricity"> · electricity {{ ELECTRICITY[d.electricity] ?? d.electricity }}</template>
            · {{ d.case ? `own design case ${d.case}` : "same plant, background only" }}
            <span class="badge" :class="verdictOf(data, d.id, category || undefined).badge" data-scenario-verdict>{{ verdictOf(data, d.id, category || undefined).label }}</span>
            <details v-if="verdictOf(data, d.id, category || undefined).reasons.length" class="verdict-reasons">
              <summary>why</summary>
              <ul><li v-for="r in verdictOf(data, d.id, category || undefined).reasons" :key="r">{{ r }}</li></ul>
            </details>
          </li>
        </ul>
      </section>

      <section v-if="allocation.length > 1" class="chart" aria-label="Allocation">
        <h2>Allocation <span class="muted">baseline, every method whose data is complete</span></h2>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr><th>method</th><th class="num">share of {{ product }}</th><th class="num">total, {{ unit }}</th><th>relative to the method used</th></tr>
            </thead>
            <tbody>
              <tr v-for="a in allocation" :key="a.method" :data-method="a.method" :class="{ used: a.current }">
                <td>{{ a.method }}<span v-if="a.current" class="badge info">used</span></td>
                <td class="num">{{ a.share !== null ? shareText(a.share) : "" }}</td>
                <td class="num">{{ a.total !== null ? impactText(a.total) : "" }}</td>
                <td>
                  <span v-if="a.relative !== null" class="relative">
                    <span class="relative-track"><span class="relative-bar" :style="{ width: `${Math.max(0, Math.min(a.relative, 2)) * 50}%` }" /></span>
                    <span class="muted">{{ (a.relative * 100).toFixed(0) }} %</span>
                  </span>
                  <span v-else class="muted">not applicable: {{ a.problem }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="stats && scenario === BASELINE" class="chart" aria-label="Uncertainty">
        <h2>Uncertainty <span class="muted">baseline, Monte Carlo, {{ data.uncertainty?.iterations }} iterations, seed {{ data.uncertainty?.seed }}</span></h2>
        <dl class="meta">
          <dt>deterministic</dt>
          <dd>{{ impactText(stats.deterministic) }} {{ unit }}</dd>
          <dt>median, mean</dt>
          <dd>{{ impactText(stats.median) }}, {{ impactText(stats.mean) }} {{ unit }}</dd>
          <dt>95 % interval</dt>
          <dd data-interval>{{ impactText(stats.low) }} .. {{ impactText(stats.high) }} {{ unit }}</dd>
        </dl>
        <UncertaintyRange :stats="stats" :unit="unit" />
        <h3 v-if="stats.sensitivity.length">What drives it <span class="muted">Spearman rank correlation with the total</span></h3>
        <ul class="sensitivity">
          <li v-for="[name, rho] in stats.sensitivity" :key="name" :data-input="name">
            <span class="name" :title="name">{{ sensitivityLabel(data, name) }}</span>
            <span class="rho-track"><span class="rho" :class="{ negative: rho < 0 }" :style="{ width: `${Math.abs(rho) * 50}%`, left: rho < 0 ? `${50 - Math.abs(rho) * 50}%` : '50%' }" /></span>
            <span class="num">{{ rho > 0 ? "+" : "" }}{{ rho.toFixed(2) }}</span>
          </li>
        </ul>
      </section>

      <section class="chart" aria-label="Compare">
        <h2>Compare with another revision <span class="muted">baselines</span></h2>
        <label class="compare-select">
          Revision
          <select v-model="other" data-action="compare">
            <option value="">none</option>
            <optgroup v-if="choices.data.value?.branches.length" label="Branches">
              <option v-for="b in choices.data.value.branches" :key="b.name" :value="b.name">{{ b.name }}</option>
            </optgroup>
            <optgroup v-if="choices.data.value?.commits.length" label="Commits changing lca/">
              <option v-for="c in choices.data.value.commits" :key="c.sha" :value="c.sha">{{ c.short }} {{ c.subject }}</option>
            </optgroup>
          </select>
        </label>
        <p v-if="other && otherReport.loading.value" class="muted">Loading {{ other }}...</p>
        <p v-else-if="otherError" class="notice warning" data-compare-error>The LCA at {{ other }} does not compute: {{ otherError }}</p>
        <p v-else-if="other && !otherData" class="muted">No LCA at {{ other }}.</p>
        <template v-if="otherData">
          <div class="table-wrap">
            <table class="data" aria-label="Totals compared">
              <thead>
                <tr><th>category</th><th class="num">this</th><th class="num">{{ other.slice(0, 12) }}</th><th class="num">change</th></tr>
              </thead>
              <tbody>
                <tr v-for="r in compared" :key="r.key" :data-compare="r.key">
                  <td>{{ r.label }}</td>
                  <td class="num">{{ r.value === null ? "absent" : impactText(r.value) }}</td>
                  <td class="num">{{ r.other === null ? "absent" : impactText(r.other) }}</td>
                  <td v-if="r.delta === null" class="muted">{{ r.note }}</td>
                  <td v-else class="num" :class="{ bad: r.delta > 0, good: r.delta < 0 }">{{ signed(r.delta) }}<template v-if="r.other"> ({{ percent(r.delta, r.other) }})</template></td>
                </tr>
              </tbody>
            </table>
          </div>
          <h3 v-if="changes.length">Largest changes, {{ categoryInfo?.title || category }}</h3>
          <div v-if="changes.length" class="table-wrap">
            <table class="data" aria-label="Contributions compared">
              <thead>
                <tr><th>flow</th><th class="num">this</th><th class="num">{{ other.slice(0, 12) }}</th><th class="num">change</th></tr>
              </thead>
              <tbody>
                <tr v-for="r in changes" :key="r.key" :data-change="r.key">
                  <td>{{ r.label }} <code class="muted">{{ r.key }}</code></td>
                  <td class="num">{{ impactText(r.value!) }}</td>
                  <td class="num">{{ impactText(r.other!) }}</td>
                  <td class="num" :class="{ bad: r.delta! > 0, good: r.delta! < 0 }">{{ signed(r.delta!) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="otherData.functional_unit !== data.functional_unit" class="notice warning">The functional units differ ({{ data.functional_unit }} and {{ otherData.functional_unit }}): the totals do not compare.</p>
        </template>
      </section>

      <section class="table-section" aria-label="Contribution table">
        <h2>Contribution table <span class="muted">{{ scenario }}</span></h2>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr><th>flow</th><th>phase</th><th class="num">quantity</th><th class="num">factor</th><th>background</th><th>status</th><th>location</th><th>source</th><th class="num">impact</th><th class="num">share</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in rows" :key="r.key" :data-key="r.key">
                <td>{{ labelOf(data, r.key) }} <code class="muted">{{ r.key }}</code></td>
                <td>{{ r.phase }}</td>
                <td class="num">{{ impactText(r.quantity) }} {{ r.unit }}</td>
                <td class="num">{{ impactText(r.factor) }} /{{ r.unit }}</td>
                <td class="muted" :title="r.source">{{ r.basis }}<template v-if="r.year"> · {{ r.year }}</template></td>
                <td data-status><span v-if="r.status" class="badge" :class="statusClass(r.status)" :title="r.source">{{ r.status }}</span></td>
                <td data-location class="muted">{{ r.location ?? "" }}</td>
                <td data-source-id class="muted">{{ r.source_id ?? "" }}</td>
                <td class="num">{{ impactText(r.value) }}</td>
                <td class="num">{{ standing && categoryTotal ? shareText(r.value / categoryTotal) : "" }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="gaps.length" class="table-section" aria-label="Gaps">
        <h2>Gaps <span class="muted">{{ scenario }}, {{ categoryInfo?.title || category }}: excluded from the total, never counted as 0</span></h2>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr><th>flow</th><th>phase</th><th class="num">quantity per {{ data.functional_unit }}</th><th>why</th></tr>
            </thead>
            <tbody>
              <tr v-for="g in gaps" :key="`${g.phase}|${g.key}|${g.reason}`" data-gap>
                <td><code>{{ g.key }}</code></td>
                <td>{{ g.phase }}</td>
                <td class="num">{{ g.quantity === null ? "unknown" : `${quantity(g.quantity)} ${g.unit}` }}</td>
                <td>{{ gapText(g) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="muted hint">How much they would add is unknown: no coverage percentage is given, as there is no defensible denominator.</p>
      </section>

      <section v-if="outside.length" class="table-section" aria-label="Outside the methods">
        <h2>Outside the methods <span class="muted">{{ scenario }}, {{ categoryInfo?.title || category }}</span></h2>
        <p class="muted hint">A flow a method does not list contributes nothing to that category by the method's definition; these are no gaps.</p>
        <ul>
          <li v-for="g in outside" :key="`${g.phase}|${g.key}|${g.reason}`"><code>{{ g.key }}</code> {{ g.quantity === null ? "" : `${quantity(g.quantity)} ${g.unit}` }} <span class="muted">{{ g.detail }}</span></li>
        </ul>
      </section>

      <section v-if="data.sources?.length" class="table-section" aria-label="Sources">
        <h2>Sources <span class="muted">the background data and their terms</span></h2>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr><th>source</th><th>version</th><th>geography, year</th><th>method</th><th>licence</th><th>publication</th></tr>
            </thead>
            <tbody>
              <tr v-for="s in data.sources" :key="s.id" data-source>
                <td><a v-if="sourceHref(s.url)" :href="sourceHref(s.url) ?? undefined" target="_blank" rel="noopener noreferrer">{{ s.title }}</a><span v-else>{{ s.title }}</span> <span class="muted">({{ s.provider }})</span></td>
                <td>{{ s.version }}</td>
                <td>{{ [s.geography, s.year].filter((x) => x).join(", ") }}</td>
                <td>{{ s.method }}</td>
                <td>{{ s.licence }}</td>
                <td><span class="badge" :class="s.publication === 'public' ? 'pass' : 'warning'">{{ s.publication }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-for="s in data.sources.filter((x) => x.attribution)" :key="s.id" class="muted hint" data-attribution>{{ s.attribution }}</p>
      </section>

      <section v-if="data.limitations?.length" class="table-section" aria-label="Limitations">
        <h2>Limitations <span class="muted">what the boundary leaves out</span></h2>
        <ul>
          <li v-for="item in data.limitations" :key="item">{{ item }}</li>
        </ul>
      </section>

      <section class="table-section" aria-label="Inventory">
        <h2>Inventory <span class="muted">per {{ data.functional_unit }}</span></h2>
        <p v-if="unmapped.length" class="notice warning">Not characterised (no background in <code>lca/lca.yaml</code>): {{ unmapped.join(", ") }}</p>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr><th>flow</th><th>phase</th><th>direction</th><th class="num">per functional unit</th><th class="num">plant</th><th>provenance</th><th>background</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in data.inventory" :key="r.key" :data-inventory="r.key" :class="{ unmapped: !r.mapping }">
                <td>{{ r.title }} <code class="muted">{{ r.key }}</code></td>
                <td>{{ r.phase }}</td>
                <td>{{ r.direction }}</td>
                <td class="num">{{ impactText(r.quantity) }} {{ r.unit }}</td>
                <td class="num muted">{{ quantity(r.plant) }} {{ r.plant_unit }}</td>
                <td><span class="badge" :class="r.provenance === 'given' ? 'pass' : r.provenance === 'assumed' ? 'warning' : 'info'">{{ r.provenance }}</span></td>
                <td :class="{ bad: !r.mapping }">{{ r.mapping || "unmapped" }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="muted hint">Co-products are listed with what is made alongside one functional unit; their share of the burdens is the allocation above.</p>
      </section>

      <LciReadiness :report="data" />

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
    </template>
  </div>
</template>

<style scoped>
.hint {
  margin: var(--space-1) 0 0;
  font-size: var(--text-sm);
}
.meta {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 2px var(--space-3);
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
}
.meta dt {
  color: var(--fg-muted);
}
.meta dd {
  margin: 0;
}
.toolbar label {
  display: inline-flex;
  gap: var(--space-1);
  align-items: center;
  font-size: var(--text-sm);
  color: var(--fg-muted);
}
.toolbar select {
  padding: 3px 6px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--fg);
  font: inherit;
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
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
  font-size: var(--text-sm);
}
.card-title {
  color: var(--fg-muted);
}
.card-value {
  font-size: var(--text-lg);
  font-variant-numeric: tabular-nums;
}
.card-value .unit {
  font-size: var(--text-sm);
  font-weight: normal;
  color: var(--fg-muted);
}
.chart {
  padding: var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  margin-bottom: var(--space-4);
}
h2 {
  font-size: var(--text);
  margin: var(--space-4) 0 var(--space-2);
  display: flex;
  gap: var(--space-2);
  align-items: baseline;
  flex-wrap: wrap;
}
.chart h2 {
  margin-top: 0;
}
h2 .muted {
  font-weight: normal;
  font-size: var(--text-sm);
}
.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.bad {
  color: var(--bad);
}
h3 {
  font-size: var(--text-sm);
  margin: var(--space-3) 0 var(--space-1);
}
h3 .muted {
  font-weight: normal;
}
.used td {
  font-weight: 600;
}
.used .badge {
  margin-left: var(--space-1);
}
.relative {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
/* 200 px is twice the method used (100 % at the middle) */
.relative-track {
  position: relative;
  display: inline-block;
  width: 200px;
  height: 10px;
  flex: 0 0 auto;
  background: var(--bg-soft);
  border-radius: 2px;
}
.relative-track::after {
  content: "";
  position: absolute;
  left: 50%;
  top: -2px;
  bottom: -2px;
  width: 1px;
  background: var(--fg-muted);
}
.relative-bar {
  display: block;
  height: 100%;
  background: var(--chart-1);
  opacity: 0.6;
  border-radius: 2px;
}
.sensitivity {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: var(--text-sm);
}
.sensitivity li {
  display: grid;
  grid-template-columns: minmax(140px, 2fr) 3fr 48px;
  gap: var(--space-2);
  align-items: center;
}
.sensitivity .name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rho-track {
  position: relative;
  height: 10px;
  background: var(--bg-soft);
  border-left: 1px solid transparent;
}
.rho-track::after {
  content: "";
  position: absolute;
  left: 50%;
  top: -2px;
  bottom: -2px;
  width: 1px;
  background: var(--fg-muted);
}
.rho {
  position: absolute;
  top: 0;
  bottom: 0;
  background: var(--bad);
  opacity: 0.7;
}
.rho.negative {
  background: var(--ok);
}
.compare-select {
  display: inline-flex;
  gap: var(--space-1);
  align-items: center;
  font-size: var(--text-sm);
  color: var(--fg-muted);
  margin-bottom: var(--space-2);
}
.compare-select select {
  padding: 3px 6px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--fg);
  font: inherit;
  max-width: 420px;
}
.good {
  color: var(--ok);
}
.table-section table td {
  font-size: var(--text-sm);
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
.warn-text {
  color: var(--warn, var(--fg));
  font-size: var(--text-sm);
}
.scenario-details {
  margin: var(--space-2) 0 0;
  padding-left: 1.2em;
  font-size: var(--text-sm);
}
</style>
