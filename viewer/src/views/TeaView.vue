<script setup lang="ts">
/**
 * The techno-economic analysis (`GET /api/tea`, `cheme assess tea`): the decision and its verdict,
 * the basis, the results, the capital and operating cost, the cash flow, scenarios, tornado,
 * break-even values, the Monte Carlo, the inputs and the findings. Core computes everything; the
 * page states it (`src/lib/tea.ts`). Sections render only when the payload has their data, and any
 * array of records core adds later shows as a table at the end.
 */
import { computed, ref, watch } from "vue";
import { api, ApiError, type Finding, type TeaReport } from "@/api";
import LoadState from "@/components/LoadState.vue";
import FindingsList from "@/components/FindingsList.vue";
import UncertaintyRange from "@/components/UncertaintyRange.vue";
import TeaBars from "@/components/TeaBars.vue";
import CashflowChart from "@/components/CashflowChart.vue";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { shortRev } from "@/lib/format";
import {
  basisRows,
  breakEvenRows,
  capexBuildUp,
  cashflowCell,
  cashflowChart,
  cashflowColumns,
  cashflowScale,
  cellText,
  costColour,
  costOfProduction,
  eventScheduleText,
  lineRows,
  lineLabel,
  linePriceText,
  operationRows,
  rhoWorsens,
  scenarioMetrics,
  categoryLabel,
  classCheck,
  decisionMetric,
  extraTables,
  flowRows,
  inputLabel,
  inputValueText,
  keyLabel,
  metricLabel,
  metricText,
  metricTitle,
  moneyText,
  multiplierText,
  numberText,
  opexRows,
  percentText,
  priceText,
  probabilityText,
  rangeGeometry,
  rateText,
  resultsOf,
  scenarioBars,
  scenarioRows,
  statisticOf,
  statisticsOf,
  statisticText,
  toIntervalStats,
  tornadoBars,
  tornadoRows,
  unpricedFlows,
  verdict,
  CASHFLOW_FRACTION_COLUMNS,
  CASHFLOW_TEXT_COLUMNS,
} from "@/lib/tea";

const { rev, withRev } = useRev();

/** The TEA at `rev`, or null when there is no `estimate/tea.yaml` there (a 404); a 422 is an error. */
const report = useAsync<TeaReport | null>(async (signal) => {
  try {
    return await api.tea(rev.value, signal);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}, rev);
const data = computed(() => report.data.value ?? null);
const missing = computed(() => !report.loading.value && !report.error.value && report.data.value === null);

const currency = computed(() => data.value?.currency ?? "");
const metric = computed(() => (data.value ? decisionMetric(data.value) : "npv"));
const results = computed(() => (data.value ? resultsOf(data.value) : {}));
const hasResults = computed(() => Object.keys(results.value).length > 0);
const decided = computed(() => (data.value ? verdict(data.value) : null));
const aace = computed(() => (data.value ? classCheck(data.value) : null));
const basis = computed(() => (data.value ? basisRows(data.value) : []));
const fmt = (m: string) => (v: number | null | undefined) => (data.value ? metricText(data.value, m, v) : "");
const money = (v: number | null | undefined) => moneyText(v, currency.value);
const wholeMoney = (v: number | null | undefined) => moneyText(v, currency.value, false);

/** The results cards: the decision metric first, then the rest. */
const cards = computed(() => {
  const r = results.value;
  const all = [
    { key: "npv", value: r.npv, note: [data.value?.basis?.discount_rate ? `at ${percentText(Number(data.value.basis.discount_rate))}` : "", unpricedMain.value].filter(Boolean).join("; ") },
    { key: "irr", value: r.irr, note: [r.irr === null ? "no rate makes the NPV 0" : "", unpricedMain.value].filter(Boolean).join("; ") },
    { key: "lcop", value: r.lcop, note: data.value?.basis?.product ? `of ${data.value.basis.product}` : "" },
    { key: "cash_cost", value: r.cash_cost, note: "operating cost per unit, no capital charge" },
    ...(r.lcop_unsubsidised !== null && r.lcop_unsubsidised !== undefined ? [{ key: "lcop_unsubsidised", value: r.lcop_unsubsidised, note: "the LCOP without incentives" }] : []),
    { key: "payback_years", value: r.payback_years, note: r.payback_years === null ? "not paid back in the life" : "discounted" },
    { key: "fixed_capital", value: r.fixed_capital, note: r.working_capital !== undefined && r.working_capital !== null ? `+ ${money(r.working_capital)} working capital` : "" },
  ].filter((c) => c.key in r);
  return [...all.filter((c) => c.key === metric.value), ...all.filter((c) => c.key !== metric.value)];
});
/** NPV and IRR leave out the main product's revenue when it has no price (an LCOP study). */
const unpricedMain = computed(() => (results.value.main_priced === false ? "without the main product's revenue (it has no price)" : ""));
const perYear = computed(() =>
  [
    { key: "revenue_per_year", label: "Revenue", value: results.value.revenue_per_year },
    { key: "variable_cost_per_year", label: "Variable cost", value: results.value.variable_cost_per_year },
    { key: "fixed_cost_per_year", label: "Fixed cost", value: results.value.fixed_cost_per_year },
  ].filter((c) => c.value !== undefined && c.value !== null),
);
function cardText(key: string, value: number | null | undefined): string {
  if (!data.value) return "";
  if (key === "payback_years") return value === null || value === undefined ? "never" : `${numberText(value, 3)} a`;
  return metricText(data.value, key, value);
}

const capex = computed(() => (data.value ? capexBuildUp(data.value) : null));
const range = computed(() => (data.value ? rangeGeometry(data.value) : null));
const pct = (v: number) => `${(Math.max(0, Math.min(1, v)) * 100).toFixed(2)}%`;
const signedPercent = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(0)} %`;

const flows = computed(() => (data.value ? flowRows(data.value) : []));
const unpriced = computed(() => (data.value ? unpricedFlows(data.value) : []));
const opex = computed(() => (data.value ? opexRows(data.value) : []));
const lines = computed(() => (data.value ? lineRows(data.value) : []));
const variable = computed(() => data.value?.variable ?? []);
const emissions = computed(() => data.value?.emissions ?? null);
const events = computed(() => data.value?.events ?? []);
const cost = computed(() => (data.value ? costOfProduction(data.value) : null));
/** The operation's rows the basis does not already say (hours and life are in `basis.operation`). */
const operation = computed(() => {
  if (!data.value) return [];
  const rows = operationRows(data.value);
  return data.value.basis?.operation ? rows.filter((r) => r.key !== "hours_per_year" && r.key !== "life_years") : rows;
});
const perCase = (f: { per_case?: Record<string, number | null> }) =>
  Object.entries(f.per_case ?? {})
    .map(([c, rate]) => `${c} ${numberText(rate)}`)
    .join(", ");
/** What a variable item's amount is per: an hour, a batch, a kg or kWh of its flow. */
const amountBasis = (per: string | undefined) => {
  if (!per || per === "hour" || per === "batch") return per ?? "";
  return data.value?.flows?.find((f) => f.key === per)?.kind === "energy" ? "kWh" : "kg";
};
const unitText = (v: number | null | undefined) => (data.value ? metricText(data.value, "lcop", v) : "");
const scenarioColumns = computed(() => (data.value ? scenarioMetrics(data.value) : []));

const cashflow = computed(() => (data.value ? cashflowChart(data.value) : null));
const columns = computed(() => (data.value ? cashflowColumns(data.value) : []));
const scale = computed(() => (data.value ? cashflowScale(data.value) : { factor: 1, label: "" }));
const isNumberColumn = (c: string) => !CASHFLOW_TEXT_COLUMNS.has(c);
const columnLabel = (c: string) => (CASHFLOW_FRACTION_COLUMNS.has(c) ? `${keyLabel(c)}, %` : keyLabel(c));

const scenarios = computed(() => (data.value ? scenarioRows(data.value) : []));
const scenarioChart = computed(() => (data.value ? scenarioBars(data.value) : null));
const tornado = computed(() => (data.value ? tornadoRows(data.value) : []));
const tornadoChart = computed(() => (data.value ? tornadoBars(data.value) : null));
const turns = computed(() => (data.value ? breakEvenRows(data.value) : []));

const statistic = ref("");
const stats = computed(() => (data.value ? statisticsOf(data.value) : []));
watch(
  data,
  (d) => {
    if (!d) return;
    const ids = statisticsOf(d).map((s) => s.metric);
    if (!ids.includes(statistic.value)) statistic.value = ids.includes(decisionMetric(d)) ? decisionMetric(d) : (ids[0] ?? "");
  },
  { immediate: true },
);
const stat = computed(() => (data.value && statistic.value ? statisticOf(data.value, statistic.value) : null));
const interval = computed(() => toIntervalStats(stat.value));
const statFormat = (v: number | null | undefined) => (data.value && stat.value ? statisticText(data.value, stat.value, v) : "");

const extras = computed(() => (data.value ? extraTables(data.value) : []));
// The boundary gaps have their own section; the findings list keeps the others.
const boundary = computed(() => data.value?.boundary ?? null);
const findings = computed<Finding[]>(() => (data.value?.findings ?? []).filter((f) => !(boundary.value && f.rule.startsWith("cheme.boundary-"))));
const provenanceBadge = (p: string | undefined) => (p === "given" ? "pass" : p === "assumed" ? "warning" : "info");
</script>

<template>
  <div class="page tea">
    <h1>
      Techno-economic analysis
      <small>{{ data ? [data.currency, data.cost_year].filter(Boolean).join(" ") : "estimate/tea.yaml" }}{{ rev ? ` at ${shortRev(rev)}` : " in the working tree" }}</small>
    </h1>

    <LoadState :loading="report.loading.value && !data" :error="report.error.value" @retry="report.reload" />
    <div v-if="missing" class="notice">
      <p><strong>No TEA{{ rev ? ` at ${shortRev(rev)}` : "" }}.</strong></p>
      <p class="muted">The page shows <code>cheme assess tea</code>: write <code>estimate/tea.yaml</code> (the decision, basis, capital cost, prices with their status, source and year, finance) and commit it. See the skill <code>tea</code>.</p>
    </div>

    <template v-if="data">
      <p v-if="data.example" class="notice warning" role="note">
        The premises are an example (<code>example: true</code> in <code>estimate/tea.yaml</code>): these numbers evaluate nothing real.
      </p>

      <section class="chart decision" aria-label="Decision">
        <h2>Decision <span v-if="data.stage" class="badge stage">{{ data.stage }}</span></h2>
        <p v-if="data.decision?.question" class="question">{{ data.decision.question }}</p>
        <p v-else class="muted">No decision in <code>estimate/tea.yaml</code>: the results are not measured against a threshold.</p>
        <ul v-if="decided" class="verdict">
          <li data-verdict="threshold">
            <span class="badge" :class="decided.level">{{ decided.text }}</span>
            <span>
              {{ metricLabel(decided.metric) }} {{ fmt(decided.metric)(decided.value) }}
              <template v-if="decided.threshold !== null">
                <span class="muted">against</span> {{ decided.comparator }} {{ fmt(decided.metric)(decided.threshold) }}
              </template>
              <span v-else class="muted">(no threshold)</span>
            </span>
          </li>
          <li v-if="decided.probability !== null || decided.confidence !== null" data-verdict="confidence">
            <span class="badge" :class="decided.confident === true ? 'pass' : decided.confident === false ? 'error' : 'na'">{{ decided.confident === true ? "confident" : decided.confident === false ? "not confident enough" : "no confidence asked" }}</span>
            <span>
              <template v-if="decided.probability !== null">P(meets) {{ probabilityText(decided.probability) }}<span class="muted"> from the Monte Carlo</span></template>
              <template v-else>No Monte Carlo</template>
              <template v-if="decided.confidence !== null"><span class="muted">; the decision asks for</span> {{ probabilityText(decided.confidence) }}</template>
            </span>
          </li>
          <li v-if="aace && aace.claimed !== null" data-verdict="class">
            <span class="badge" :class="aace.matches === false ? 'warning' : aace.matches ? 'pass' : 'na'">AACE class {{ aace.claimed }}</span>
            <span>
              the capital cost's estimate class<template v-if="aace.text">, {{ aace.text }}</template>
            </span>
          </li>
        </ul>
        <template v-if="data.decision?.alternatives?.length">
          <h3>Alternatives</h3>
          <ul class="alternatives">
            <li v-for="a in data.decision.alternatives" :key="a">{{ a }}</li>
          </ul>
        </template>
      </section>

      <dl v-if="basis.length || operation.length" class="meta" aria-label="Basis">
        <template v-for="b in basis" :key="b.key">
          <dt>{{ b.label }}</dt>
          <dd :data-basis="b.key">{{ b.value }}</dd>
        </template>
        <template v-for="o in operation" :key="o.key">
          <dt>{{ o.label }}</dt>
          <dd :data-operation="o.key">{{ o.value }}</dd>
        </template>
      </dl>

      <section v-if="hasResults" class="cards" aria-label="Results">
        <div v-for="c in cards" :key="c.key" class="card" :class="{ decisive: c.key === metric }" :data-card="c.key">
          <span class="card-title" :title="metricTitle(c.key)">{{ metricLabel(c.key) }}<span v-if="c.key === metric" class="badge info">decision</span></span>
          <strong class="card-value">{{ cardText(c.key, c.value) }}</strong>
          <span v-if="c.note" class="muted">{{ c.note }}</span>
        </div>
        <div v-if="perYear.length" class="card" data-card="per-year">
          <span class="card-title">Per year, full capacity</span>
          <span v-for="p in perYear" :key="p.key" class="per-year">
            <span class="muted">{{ p.label }}</span> <span class="num">{{ money(p.value) }}</span>
          </span>
        </div>
      </section>
      <p v-else class="notice warning">No results: the TEA has no baseline (see the findings).</p>

      <section v-if="cost" class="chart" aria-label="Cost of production">
        <h2>Cost of production <span class="muted">per unit of {{ data.basis?.product ?? "the main product" }}, {{ cost.unit }}; credits (by-products) left of 0</span></h2>
        <div class="cop-bar" role="img" :aria-label="`Cost of production: ${cost.rows.map((r) => `${r.label} ${unitText(r.perUnit)}`).join(', ')}; total ${unitText(cost.total)}`">
          <span v-for="s in cost.segments" :key="s.category" class="cop-segment" :class="{ credit: s.credit }" :data-segment="s.category" :style="{ left: pct(s.from), width: pct(s.to - s.from), background: `var(--chart-${s.colour})` }" :title="`${categoryLabel(s.category)}: ${unitText(cost.rows.find((r) => r.category === s.category)?.perUnit)}`" />
          <span v-if="cost.zero > 0" class="cop-zero" :style="{ left: pct(cost.zero) }" />
        </div>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr><th>category</th><th class="num">per unit</th><th class="num">per year</th><th class="num">share of the LCOP</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in cost.rows" :key="r.category" :data-cost="r.category">
                <td class="nowrap"><span class="swatch" :style="{ background: `var(--chart-${costColour(cost, r.category)})` }" />{{ r.label }}</td>
                <td class="num" :class="{ good: (r.perUnit ?? 0) < 0 }">{{ unitText(r.perUnit) }}</td>
                <td class="num muted">{{ money(r.perYear) }}</td>
                <td class="num">{{ r.share !== null ? percentText(r.share) : "" }}</td>
              </tr>
            </tbody>
            <tfoot>
              <tr data-cost="total">
                <th>LCOP</th>
                <th class="num">{{ unitText(cost.lcop ?? cost.total) }}</th>
                <th />
                <th class="num"><span v-if="cost.lcop !== null && Math.abs(cost.total - cost.lcop) > 1e-6 * Math.max(1, Math.abs(cost.lcop))" class="badge warning" :title="`the rows sum to ${unitText(cost.total)}`">rows differ</span></th>
              </tr>
            </tfoot>
          </table>
        </div>
      </section>

      <section v-if="capex && capex.steps.length" class="chart" aria-label="Capital cost">
        <h2>Capital cost <span class="muted">{{ currency }} {{ data.cost_year }}</span></h2>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr><th>item</th><th>basis</th><th class="num">cost</th><th class="num">cumulative</th><th class="num">share</th><th>source</th></tr>
            </thead>
            <tbody>
              <tr v-for="s in capex.steps" :key="s.id" :data-capex="s.id">
                <td>{{ s.title || keyLabel(s.id) }}</td>
                <td class="muted">{{ s.basis }}</td>
                <td class="num">
                  {{ wholeMoney(s.value) }}
                  <span v-if="s.original" class="muted original" :title="`as estimated: ${moneyText(s.original.value, s.original.currency, false)}`">{{ moneyText(s.original.value, s.original.currency, false) }} as estimated</span>
                </td>
                <td class="num muted">{{ wholeMoney(s.cumulative) }}</td>
                <td class="num">{{ s.share !== null ? percentText(s.share) : "" }}</td>
                <td class="source" :title="s.source">
                  <span v-if="s.status" class="badge" :class="s.status === 'QUOTED' ? 'pass' : 'warning'">{{ s.status }}</span>
                  {{ s.source }}<template v-if="s.year"> ({{ s.year }})</template>
                </td>
              </tr>
            </tbody>
            <tfoot>
              <tr data-capex="fixed_capital">
                <th colspan="2">Fixed capital</th>
                <th class="num">{{ wholeMoney(capex.fixedCapital) }}</th>
                <th />
                <th class="num">{{ capex.fixedCapital !== null ? "100 %" : "" }}</th>
                <th><span v-if="!capex.sums" class="badge warning">the lines do not add up to it</span></th>
              </tr>
              <tr v-if="capex.workingCapital !== null" data-capex="working_capital">
                <td colspan="2">Working capital <span class="muted">(recovered at the end)</span></td>
                <td class="num">{{ wholeMoney(capex.workingCapital) }}</td>
                <td colspan="3" />
              </tr>
            </tfoot>
          </table>
        </div>
        <template v-if="range">
          <h3>Accuracy <span class="muted">AACE class {{ data.capex_range?.class ?? data.estimate_class }}</span></h3>
          <div class="aace" role="img" :aria-label="`AACE range: low ${money(range.low[0])} to ${money(range.low[1])}, high ${money(range.high[0])} to ${money(range.high[1])}, estimate ${money(range.value)}`" data-range>
            <div class="aace-track">
              <span class="aace-outer" :style="{ left: pct(range.outer[0]), width: pct(range.outer[1] - range.outer[0]) }" />
              <span class="aace-inner" :style="{ left: pct(range.inner[0]), width: pct(range.inner[1] - range.inner[0]) }" />
              <span class="aace-point" :style="{ left: pct(range.point) }" />
            </div>
            <div class="axis"><span>{{ money(range.min) }}</span><span>{{ money(range.max) }}</span></div>
          </div>
          <p class="muted hint">
            The fixed capital {{ money(range.value) }} lies, at the class's accuracy, between a low end of {{ money(range.low[0]) }} to {{ money(range.low[1]) }}
            ({{ signedPercent(range.lowPercent[0]) }} to {{ signedPercent(range.lowPercent[1]) }}) and a high end of {{ money(range.high[0]) }} to {{ money(range.high[1]) }}
            ({{ signedPercent(range.highPercent[0]) }} to {{ signedPercent(range.highPercent[1]) }}). Dark: within both ends' best case; light: up to their worst.
          </p>
        </template>
      </section>

      <section v-if="boundary" class="chart" aria-label="Boundary" data-testid="tea-boundary">
        <h2>
          Boundary
          <span class="badge" :class="boundary.complete ? 'pass' : 'warning'">{{ boundary.complete ? "no gaps found" : "gaps found" }}</span>
        </h2>
        <p v-if="!boundary.complete" class="notice warning">
          The boundary check found gaps: the operating cost counts only the flowsheet's terminals, so it may miss utilities,
          wastes or emissions. A boundary without gaps is not a complete inventory either (see what is not checked).
        </p>
        <dl class="boundary-facts">
          <template v-if="boundary.excluded_products.length">
            <dt>Counted at no cost</dt>
            <dd data-boundary="excluded">{{ boundary.excluded_products.join(", ") }} <span class="muted">(products without a category or price)</span></dd>
          </template>
          <template v-if="boundary.unassigned_duties.length">
            <dt>Duty without an energy stream</dt>
            <dd data-boundary="duties">{{ boundary.unassigned_duties.join(", ") }}</dd>
          </template>
          <template v-for="(ids, category) in boundary.categories" :key="category">
            <dt>{{ category }}</dt>
            <dd>{{ ids.join(", ") }}</dd>
          </template>
        </dl>
        <FindingsList :findings="boundary.gaps" label="Boundary gaps" title="Gaps" />
        <details class="boundary-rules">
          <summary>What the check covers</summary>
          <h3>Checked</h3>
          <ul><li v-for="c in boundary.checked" :key="c">{{ c }}</li></ul>
          <template v-if="boundary.noted.length">
            <h3>Noted (info only)</h3>
            <ul><li v-for="c in boundary.noted" :key="c">{{ c }}</li></ul>
          </template>
          <h3>Not checked</h3>
          <ul><li v-for="c in boundary.not_checked" :key="c">{{ c }}</li></ul>
        </details>
      </section>

      <section v-if="flows.length || opex.length || lines.length || events.length" class="chart" aria-label="Operating cost">
        <h2>Operating cost <span class="muted">per year at full capacity, {{ currency }}</span></h2>
        <p v-if="unpriced.length" class="notice warning" data-unpriced>
          No price, counted as free: {{ unpriced.map((f) => f.title || f.key).join(", ") }}. Give each a price, or list it under <code>free:</code> with why.
        </p>
        <template v-if="flows.length">
          <h3>Feeds and products</h3>
          <div class="table-wrap">
            <table class="data">
              <thead>
                <tr><th>flow</th><th class="num">rate</th><th>provenance</th><th class="num">price</th><th class="num" title="Revenue positive, cost negative">net per year</th><th>source</th></tr>
              </thead>
              <tbody>
                <tr v-for="f in flows" :key="f.key" :data-flow="f.key" :data-role="f.role" :class="{ unpriced: f.role === 'unpriced' }">
                  <td class="flow-name">
                    {{ f.title || f.key }}
                    <span class="sub">
                      <code class="muted">{{ f.key }}</code>
                      <span v-if="f.component" class="badge info" :title="`only ${f.component} of the flow is priced`">{{ f.component }}</span>
                      <span v-if="f.kind === 'energy'" class="badge info">energy</span>
                    </span>
                  </td>
                  <td class="num">
                    {{ rateText(f) }}
                    <span v-if="perCase(f)" class="muted original" title="Rate per flowsheet case">{{ perCase(f) }}</span>
                  </td>
                  <td><span v-if="f.provenance" class="badge" :class="provenanceBadge(f.provenance)">{{ f.provenance }}</span></td>
                  <td class="num">
                    <template v-if="f.role === 'priced'">{{ priceText(f, currency) }}</template>
                    <span v-else-if="f.role === 'free'" class="badge na" :title="f.free">free</span>
                    <span v-else-if="f.role === 'main'" class="badge info" title="The main product: the LCOP is its price">main product</span>
                    <span v-else class="badge warning" title="No price and not listed under free: counted as 0">no price</span>
                  </td>
                  <td class="num" :class="{ bad: f.direction === 'feed' || (f.per_year ?? 0) < 0 }">{{ money(f.per_year) }}</td>
                  <td class="source" :title="f.source || f.free">
                    <template v-if="f.role === 'free'">{{ f.free }}</template>
                    <template v-else>
                      <span v-if="f.status" class="badge" :class="f.status === 'QUOTED' ? 'pass' : 'warning'">{{ f.status }}</span>
                      {{ f.source }}<template v-if="f.year"> ({{ f.year }})</template>
                    </template>
                  </td>
                </tr>
              </tbody>
              <tfoot v-if="results.revenue_per_year !== undefined || results.variable_cost_per_year !== undefined">
                <tr v-if="results.revenue_per_year !== undefined">
                  <th colspan="4">Revenue</th>
                  <th class="num">{{ money(results.revenue_per_year) }}</th>
                  <th />
                </tr>
                <tr v-if="results.variable_cost_per_year !== undefined">
                  <th colspan="4">Variable cost <span class="muted">(every priced cost line below)</span></th>
                  <th class="num">{{ money(results.variable_cost_per_year) }}</th>
                  <th />
                </tr>
              </tfoot>
            </table>
          </div>
        </template>
        <template v-if="lines.length">
          <h3>Priced lines <span class="muted">what the cash flow counts per year: costs, then revenues</span></h3>
          <div class="table-wrap">
            <table class="data" aria-label="Priced lines">
              <thead>
                <tr><th>line</th><th>category</th><th class="num">per hour</th><th class="num">price</th><th class="num">per year</th></tr>
              </thead>
              <tbody>
                <tr v-for="l in lines" :key="l.key" :data-line="l.key">
                  <td class="flow-name">{{ l.label }} <span class="sub"><code class="muted">{{ l.key }}</code></span></td>
                  <td><span class="badge" :class="l.revenue ? 'pass' : 'na'">{{ categoryLabel(l.category) }}</span></td>
                  <td class="num">{{ numberText(l.rate) }} {{ l.unit }}</td>
                  <td class="num">
                    {{ linePriceText(l, currency) }}
                    <span v-if="l.profile.length" class="muted original" title="Price multipliers by operating year">profile {{ l.profile.map((m) => `× ${numberText(m, 3)}`).join(", ") }}</span>
                  </td>
                  <td class="num" :class="{ bad: !l.revenue || (l.perYear ?? 0) < 0 }">{{ money(l.perYear) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
        <template v-if="variable.length">
          <h3>Other variable costs <span class="muted">chemicals, catalysts, fees the flowsheet does not carry</span></h3>
          <div class="table-wrap">
            <table class="data" aria-label="Variable items">
              <thead>
                <tr><th>item</th><th>per</th><th class="num">amount</th><th class="num">price</th><th class="num">per hour</th><th>source</th></tr>
              </thead>
              <tbody>
                <tr v-for="v in variable" :key="v.id" :data-variable="v.id">
                  <td>{{ v.title || keyLabel(v.id) }} <span v-if="v.category" class="badge na">{{ categoryLabel(v.category) }}</span></td>
                  <td>{{ v.per ? lineLabel(data, v.per) : "" }}<template v-if="v.component"> ({{ v.component }})</template></td>
                  <td class="num">{{ numberText(v.amount) }} {{ v.unit }}<span class="muted"> /{{ amountBasis(v.per) }}</span></td>
                  <td class="num">{{ linePriceText({ price: v.price ?? null, unit: v.unit ?? "" }, currency) }}</td>
                  <td class="num">{{ numberText(v.rate) }} {{ v.unit }}</td>
                  <td class="source" :title="v.source">
                    <span v-if="v.status" class="badge" :class="v.status === 'QUOTED' ? 'pass' : 'warning'">{{ v.status }}</span>
                    {{ v.source }}<template v-if="v.year"> ({{ v.year }})</template>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
        <template v-if="emissions">
          <h3>Emissions</h3>
          <dl class="meta" data-emissions>
            <dt>emitted</dt>
            <dd>{{ numberText(emissions.t_per_year) }} t CO2-eq/a<template v-if="emissions.free_t_per_year">, of which {{ numberText(emissions.free_t_per_year) }} t free allowances</template></dd>
            <dt>cost</dt>
            <dd>{{ money(emissions.cost_per_year) }} per year, {{ unitText(emissions.per_unit) }}</dd>
          </dl>
        </template>
        <template v-if="opex.length">
          <h3>Fixed operating cost</h3>
          <div class="table-wrap">
            <table class="data">
              <thead>
                <tr><th>item</th><th>basis</th><th class="num">per year</th><th class="num">share</th><th>source</th></tr>
              </thead>
              <tbody>
                <tr v-for="o in opex" :key="o.id" :data-opex="o.id">
                  <td>{{ o.title || keyLabel(o.id) }}</td>
                  <td class="muted">{{ o.basis }}</td>
                  <td class="num">{{ money(o.per_year) }}</td>
                  <td class="num">{{ o.share !== null ? percentText(o.share) : "" }}</td>
                  <td class="source" :title="o.source">
                    <span v-if="o.status" class="badge" :class="o.status === 'QUOTED' ? 'pass' : 'warning'">{{ o.status }}</span>
                    {{ o.source }}<template v-if="o.year"> ({{ o.year }})</template>
                  </td>
                </tr>
              </tbody>
              <tfoot v-if="results.fixed_cost_per_year !== undefined">
                <tr>
                  <th colspan="2">Fixed cost</th>
                  <th class="num">{{ money(results.fixed_cost_per_year) }}</th>
                  <th colspan="2" />
                </tr>
              </tfoot>
            </table>
          </div>
        </template>
        <template v-if="events.length">
          <h3>Events <span class="muted">replacements, turnarounds, one-off costs; expensed ones are the cash flow's periodic column</span></h3>
          <div class="table-wrap">
            <table class="data" aria-label="Events">
              <thead>
                <tr><th>event</th><th>kind</th><th class="num">amount</th><th>when</th><th class="num">downtime</th><th>treatment</th><th>source</th></tr>
              </thead>
              <tbody>
                <tr v-for="e in events" :key="e.id" :data-event="e.id">
                  <td>{{ e.title || keyLabel(e.id) }}</td>
                  <td>{{ e.kind ? keyLabel(e.kind) : "" }}</td>
                  <td class="num" :class="{ good: (e.amount ?? 0) < 0 }">{{ money(e.amount) }}</td>
                  <td>{{ eventScheduleText(e) }}</td>
                  <td class="num">{{ e.downtime_days ? `${numberText(e.downtime_days)} d` : "" }}</td>
                  <td>{{ e.treatment }}</td>
                  <td class="source" :title="e.source">
                    <span v-if="e.status" class="badge" :class="e.status === 'QUOTED' ? 'pass' : 'warning'">{{ e.status }}</span>
                    {{ e.source }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </section>

      <section v-if="cashflow" class="chart" aria-label="Cash flow">
        <h2>Cash flow <span class="muted">{{ cashflow.bars.length }} years, {{ currency }}; the line is the discounted cumulative (the NPV at the end)</span></h2>
        <CashflowChart :chart="cashflow" :format="money" label="Cash flow per year" />
        <details class="cashflow-table">
          <summary data-action="cashflow-table">Table <span class="muted">{{ scale.label ? `in ${scale.label}` : "" }}</span></summary>
          <div class="table-wrap">
            <table class="data" aria-label="Cash flow table">
              <thead>
                <tr>
                  <th v-for="c in columns" :key="c" :class="{ num: isNumberColumn(c) }">{{ columnLabel(c) }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in data.cashflow" :key="row.year" :data-year="row.year" :class="row.phase">
                  <td v-for="c in columns" :key="c" :class="{ num: isNumberColumn(c), bad: isNumberColumn(c) && !CASHFLOW_FRACTION_COLUMNS.has(c) && typeof row[c] === 'number' && (row[c] as number) < 0 }">{{ cashflowCell(row, c, scale.factor) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </details>
      </section>

      <section v-if="scenarios.length > 1" class="chart" aria-label="Scenarios">
        <h2>Scenarios <span class="muted">{{ metricLabel(metric) }} against the baseline</span></h2>
        <TeaBars v-if="scenarioChart" :chart="scenarioChart" label="Scenario bars" :format="fmt(metric)" :legend="[{ tone: 'good', label: 'meets' }, { tone: 'bad', label: 'does not meet' }]" />
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr><th>scenario</th><th class="num">fixed capital</th><th v-for="m in scenarioColumns" :key="m" class="num">{{ metricLabel(m) }}</th><th class="num">change in {{ metricLabel(metric) }}</th><th>verdict</th></tr>
            </thead>
            <tbody>
              <tr v-for="s in scenarios" :key="s.id" :data-scenario="s.id" :class="{ baseline: s.baseline }">
                <td :title="s.source">{{ s.title || s.id }}<span v-if="s.source" class="muted source-line">{{ s.source }}</span></td>
                <td class="num">{{ money(s.fixed_capital) }}</td>
                <td v-for="m in scenarioColumns" :key="m" class="num" :class="{ decisive: m === metric }">{{ fmt(m)((s as unknown as Record<string, number | null>)[m]) }}</td>
                <td class="num">{{ s.delta === null ? "" : `${s.delta > 0 ? "+" : ""}${fmt(metric)(s.delta)}` }}</td>
                <td><span class="badge" :class="s.meets === true ? 'pass' : s.meets === false ? 'error' : 'na'">{{ s.meets === true ? "meets" : s.meets === false ? "does not meet" : "no verdict" }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="tornadoChart" class="chart" aria-label="Tornado">
        <h2>Tornado <span class="muted">{{ metricLabel(metric) }} with each input at its low and high end, the others at base</span></h2>
        <TeaBars :chart="tornadoChart" label="Tornado bars" :format="fmt(metric)" :legend="[{ tone: 'low', label: 'input low' }, { tone: 'high', label: 'input high' }]" />
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr><th>input</th><th>range from</th><th class="num">low</th><th class="num">{{ metricLabel(metric) }} at low</th><th class="num">high</th><th class="num">{{ metricLabel(metric) }} at high</th></tr>
            </thead>
            <tbody>
              <tr v-for="t in tornado" :key="t.input" :data-tornado="t.input">
                <td :title="t.input">{{ t.label }}</td>
                <td class="muted">{{ t.basis }}</td>
                <td class="num muted">{{ multiplierText(t.low) }}</td>
                <td class="num">{{ fmt(metric)(t.atLow) }}</td>
                <td class="num muted">{{ multiplierText(t.high) }}</td>
                <td class="num">{{ fmt(metric)(t.atHigh) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="turns.length" class="chart" aria-label="Break-even">
        <h2>Break-even <span class="muted">the value of each input, the others at base, at which {{ metricLabel(metric) }} reaches the threshold</span></h2>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr><th>input</th><th class="num">base</th><th class="num">break-even</th><th class="num">of the base</th></tr>
            </thead>
            <tbody>
              <tr v-for="t in turns" :key="t.input" :data-turn="t.input" :class="{ never: t.never }">
                <td :title="t.input">{{ t.label }}</td>
                <td class="num">{{ inputValueText(data, t.base, t.unit) }}</td>
                <td class="num">
                  <span v-if="t.never" class="muted" title="No value of this input alone reaches the threshold">never</span>
                  <template v-else>{{ t.text }}</template>
                </td>
                <td class="num muted">{{ t.multiplierText }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="stats.length" class="chart" aria-label="Uncertainty">
        <h2>
          Uncertainty
          <span class="muted">Monte Carlo<template v-if="data.uncertainty?.iterations">, {{ data.uncertainty.iterations }} iterations</template><template v-if="data.uncertainty?.seed !== undefined && data.uncertainty?.seed !== null">, seed {{ data.uncertainty.seed }}</template></span>
        </h2>
        <div class="toolbar">
          <label v-if="stats.length > 1">
            Metric
            <select v-model="statistic" data-action="statistic">
              <option v-for="s in stats" :key="s.metric" :value="s.metric">{{ metricLabel(s.metric) }}</option>
            </select>
          </label>
        </div>
        <template v-if="stat">
          <dl class="meta">
            <dt>deterministic</dt>
            <dd>{{ statFormat(stat.deterministic) }}</dd>
            <dt>P10, P50, P90</dt>
            <dd data-interval>{{ statFormat(stat.p10) }}, {{ statFormat(stat.p50) }}, {{ statFormat(stat.p90) }}</dd>
            <dt>mean</dt>
            <dd>{{ statFormat(stat.mean) }}</dd>
            <template v-if="stat.valid !== undefined && stat.valid !== null && data.uncertainty?.iterations && stat.valid < data.uncertainty.iterations">
              <dt>valid</dt>
              <dd>{{ stat.valid }} of {{ data.uncertainty.iterations }} iterations (the metric does not exist in the others)</dd>
            </template>
          </dl>
          <UncertaintyRange v-if="interval" :stats="interval" :unit="stat.unit ?? ''" label="P10 to P90" :format="statFormat" />
          <h3 v-if="stat.sensitivity?.length">What drives it <span class="muted">Spearman rank correlation with {{ metricLabel(stat.metric) }}</span></h3>
          <ul v-if="stat.sensitivity?.length" class="sensitivity">
            <li v-for="[name, rho] in stat.sensitivity" :key="name" :data-input="name">
              <span class="name" :title="name">{{ inputLabel(data, name) }}</span>
              <span class="rho-track"><span class="rho" :class="{ better: !rhoWorsens(stat.metric, rho) }" :style="{ width: `${Math.abs(rho) * 50}%`, left: rho < 0 ? `${50 - Math.abs(rho) * 50}%` : '50%' }" /></span>
              <span class="num">{{ rho > 0 ? "+" : "" }}{{ rho.toFixed(2) }}</span>
            </li>
          </ul>
        </template>
      </section>

      <section v-if="data.inputs?.length" class="table-section" aria-label="Inputs">
        <h2>Inputs <span class="muted">what the sensitivity, break-even and Monte Carlo vary</span></h2>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr><th>input</th><th class="num">value</th><th>status</th><th>source</th></tr>
            </thead>
            <tbody>
              <tr v-for="i in data.inputs" :key="i.id" :data-input-row="i.id">
                <td>{{ inputLabel(data, i.id) }} <code class="muted">{{ i.id }}</code></td>
                <td class="num">{{ inputValueText(data, i.value, i.unit) }}</td>
                <td><span v-if="i.status" class="badge" :class="i.status === 'QUOTED' || i.status === 'given' ? 'pass' : i.status === 'calculated' ? 'info' : 'warning'">{{ i.status }}</span></td>
                <td class="source" :title="i.source">{{ i.source }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-for="t in extras" :key="t.key" class="table-section" :aria-label="t.title" :data-extra="t.key">
        <h2>{{ t.title }}</h2>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr><th v-for="c in t.columns" :key="c">{{ keyLabel(c) }}</th></tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in t.rows" :key="i">
                <td v-for="c in t.columns" :key="c" :class="{ num: typeof row[c] === 'number' }">{{ cellText(row[c]) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <FindingsList :findings="findings" label="Findings" />
      <p class="muted hint">
        From <RouterLink :to="{ name: 'file', params: { path: ['estimate', 'tea.yaml'] }, query: withRev() }">estimate/tea.yaml</RouterLink>; <code>cheme assess tea</code> writes the same numbers.
      </p>
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
  overflow-wrap: anywhere;
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
.decision .question {
  margin: 0 0 var(--space-2);
  font-size: var(--text-lg);
}
.verdict {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  font-size: var(--text-sm);
}
.verdict li {
  display: flex;
  gap: var(--space-2);
  align-items: baseline;
  flex-wrap: wrap;
}
.alternatives {
  margin: 0;
  padding-left: var(--space-5, 20px);
  font-size: var(--text-sm);
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
.card.decisive {
  border-color: var(--info);
}
.card-title {
  color: var(--fg-muted);
  display: flex;
  gap: var(--space-1);
  align-items: center;
}
.card-value {
  font-size: var(--text-lg);
  font-variant-numeric: tabular-nums;
}
.per-year {
  display: flex;
  justify-content: space-between;
  gap: var(--space-2);
}
.chart {
  padding: var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  margin-bottom: var(--space-4);
  min-width: 0;
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
h3 {
  font-size: var(--text-sm);
  margin: var(--space-3) 0 var(--space-1);
}
h3 .muted {
  font-weight: normal;
}
.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.bad {
  color: var(--bad);
}
table.data td,
table.data th {
  font-size: var(--text-sm);
}
.nowrap {
  white-space: nowrap;
}
td.decisive {
  font-weight: 600;
}
.flow-name .sub {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  align-items: center;
}
.original {
  display: block;
  font-size: 11.5px;
}
.good {
  color: var(--ok);
}
.swatch {
  display: inline-block;
  width: 10px;
  height: 10px;
  margin-right: var(--space-1);
  border-radius: 2px;
}
.cop-bar {
  position: relative;
  height: 22px;
  margin-bottom: var(--space-2);
  background: var(--bg-soft);
  border-radius: var(--radius);
  overflow: hidden;
}
.cop-segment {
  position: absolute;
  top: 0;
  bottom: 0;
  border-right: 1px solid var(--surface);
}
.cop-segment.credit {
  opacity: 0.55;
}
.cop-zero {
  position: absolute;
  top: 0;
  bottom: 0;
  border-left: 2px solid var(--fg);
}
.source {
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--fg-muted);
}
.source-line {
  display: block;
  font-size: 11.5px;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
tr.baseline td {
  font-weight: 600;
}
tr.unpriced td:first-child {
  border-left: 3px solid var(--warn);
}
tr.construction td {
  color: var(--fg-muted);
}
.aace {
  font-size: var(--text-sm);
}
.aace-track {
  position: relative;
  height: 18px;
  background: var(--bg-soft);
  border-radius: var(--radius);
}
.aace-outer,
.aace-inner {
  position: absolute;
  top: 4px;
  bottom: 4px;
  background: var(--chart-2);
  border-radius: 3px;
}
.aace-outer {
  opacity: 0.3;
}
.aace-inner {
  opacity: 0.7;
}
.aace-point {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  margin-left: -1px;
  background: var(--fg);
}
.axis {
  display: flex;
  justify-content: space-between;
  color: var(--fg-muted);
  font-variant-numeric: tabular-nums;
}
.cashflow-table {
  margin-top: var(--space-2);
}
.cashflow-table summary {
  cursor: pointer;
  font-size: var(--text-sm);
  font-weight: 600;
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
  grid-template-columns: minmax(120px, 2fr) 3fr 48px;
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
.rho.better {
  background: var(--ok);
}
@media (max-width: 560px) {
  .meta {
    grid-template-columns: 1fr;
  }
  .meta dd {
    margin-bottom: var(--space-1);
  }
  .source {
    max-width: 200px;
  }
}
.boundary-facts {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 2px var(--space-4);
  margin: 0 0 var(--space-2);
  font-size: var(--text-sm);
}
.boundary-facts dt {
  color: var(--fg-muted);
}
.boundary-facts dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.boundary-rules {
  margin-top: var(--space-2);
  font-size: var(--text-sm);
}
.boundary-rules summary {
  cursor: pointer;
}
</style>
