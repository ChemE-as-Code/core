<script setup lang="ts">
/**
 * The equipment estimate (`GET /api/estimate/equipment`, `cheme assess equipment`): totals with
 * the AACE class's accuracy range, a line per listed item with its status, size and where the
 * size comes from, the project's own costs and the findings.
 */
import { computed, ref } from "vue";
import type { EquipmentEstimate } from "@/api";
import { useRev } from "@/lib/useRev";
import { pathSegments } from "@/lib/format";
import { accuracyBand, costLineMatches, costStatus, sizeAssumed, STATUS_CHIPS, statusSums, wholeMoney, type CostStatus } from "@/lib/equipmentCost";

const props = defineProps<{
  estimate: EquipmentEstimate;
  /** Tag -> its datasheet's repo path. */
  datasheets: ReadonlyMap<string, string>;
  /** The layout view has something to select the tag in. */
  hasLayout: boolean;
}>();

const { withRev } = useRev();
const currency = computed(() => props.estimate.currency || "");
const totals = computed(() => props.estimate.totals);
const sums = computed(() => statusSums(props.estimate.lines));
const sumOf = (s: CostStatus) => sums.value.find((x) => x.status === s);
const bareItems = computed(() => totals.value.bare_module_items ?? sumOf("bare")?.count ?? 0);
const purchasedItems = computed(() => props.estimate.lines.filter((l) => l.purchased !== null).length);
const band = computed(() => accuracyBand(totals.value.bare_module, props.estimate.accuracy));

const query = ref("");
const only = ref<CostStatus | null>(null);
const lines = computed(() => props.estimate.lines.filter((l) => (!only.value || costStatus(l) === only.value) && costLineMatches(l, query.value)));
function toggle(s: CostStatus): void {
  only.value = only.value === s ? null : s;
}
const num = (v: number | null, digits = 3) => (v === null ? "" : v.toLocaleString("en", { maximumFractionDigits: digits }));
/** The short form of a size source: where it is read (before its own source in brackets). */
const sourceShort = (s: string) => s.replace(/\s*\(.*$/, "");
</script>

<template>
  <section class="equipment" aria-label="Equipment estimate">
    <p class="muted hint">
      Purchased and bare module cost of every item of the equipment list from Turton et al.'s CAPCOST correlations (<code>cheme assess equipment</code>), at the base
      CEPCI {{ estimate.base.cepci }} ({{ estimate.base.year }})<template v-if="estimate.index">, escalated to CEPCI {{ estimate.index.value }} ({{ estimate.index.year }})</template>.
      The bare module cost includes installation and indirects: do not add the take-off's factor estimate on top for the same scope.
    </p>
    <p v-if="!estimate.index" class="notice warning" role="note" data-no-index>
      No cost index (<code>cost_index</code> in <code>estimate/cost-basis.yaml</code>): the costs stay at {{ estimate.base.year }} (CEPCI {{ estimate.base.cepci }}).
    </p>
    <p v-else-if="estimate.index.source" class="muted hint index-source" :title="estimate.index.source">Index: {{ estimate.index.source }}</p>

    <section class="cards" aria-label="Equipment totals">
      <div class="card" data-total="bare_module">
        <span class="card-title">bare module</span>
        <strong class="card-value">{{ wholeMoney(totals.bare_module, currency) }}</strong>
        <span class="muted">{{ bareItems }} of {{ totals.items }} items</span>
      </div>
      <div class="card" data-total="purchased">
        <span class="card-title">purchased</span>
        <strong class="card-value">{{ wholeMoney(totals.purchased, currency) }}</strong>
        <span class="muted">{{ purchasedItems }} of {{ totals.items }} items</span>
      </div>
      <div class="card" data-total="class">
        <span class="card-title">AACE class {{ estimate.estimate_class }}</span>
        <strong class="card-value accuracy">{{ estimate.accuracy.low }} / {{ estimate.accuracy.high }}</strong>
        <span class="muted">expected accuracy (18R-97)</span>
      </div>
    </section>
    <p v-if="band && totals.bare_module" class="muted hint" data-band>
      On the bare module total: the low end lies between {{ wholeMoney(band.low[0]) }} and {{ wholeMoney(band.low[1]) }}, the high end between
      {{ wholeMoney(band.high[0]) }} and {{ wholeMoney(band.high[1]) }} {{ currency }}<template v-if="bareItems < totals.items">, for the {{ bareItems }} items it covers</template>.
    </p>

    <div class="toolbar">
      <div class="chips" role="group" aria-label="Status">
        <button
          v-for="s in sums"
          :key="s.status"
          type="button"
          class="badge chip"
          :class="[STATUS_CHIPS[s.status].badge, { off: only && only !== s.status }]"
          :aria-pressed="only === s.status"
          :title="STATUS_CHIPS[s.status].title"
          :data-status="s.status"
          @click="toggle(s.status)"
        >
          {{ STATUS_CHIPS[s.status].label }} {{ s.count }}
        </button>
      </div>
      <span class="spacer" />
      <input v-model="query" class="filter" type="search" placeholder="Filter: K-4101, pump, ASSUMED…" aria-label="Filter the items" />
    </div>

    <p v-if="!lines.length" class="muted">No item matches.</p>
    <div v-else class="table-wrap">
      <table class="data lines" aria-label="Equipment items">
        <thead>
          <tr>
            <th>tag</th>
            <th>status</th>
            <th>correlation</th>
            <th class="num">size</th>
            <th>size from</th>
            <th class="num" :title="`Purchased cost at CEPCI ${estimate.base.cepci}`">Cp0 {{ estimate.base.year }}</th>
            <th class="num">Fp</th>
            <th class="num">Fm</th>
            <th class="num">FBM</th>
            <th class="num">purchased</th>
            <th class="num">bare module</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="l in lines" :key="l.tag" :data-tag="l.tag" :data-status="costStatus(l)">
            <td class="tag-cell">
              <strong class="tag">{{ l.tag }}</strong>
              <span class="muted type">{{ l.type }}</span>
              <span class="links">
                <RouterLink v-if="datasheets.has(l.tag)" :to="{ name: 'datasheet', params: { tag: l.tag }, query: withRev() }" data-link="datasheet" title="The item's datasheet">datasheet</RouterLink>
                <RouterLink v-if="hasLayout" :to="{ name: 'layout', query: withRev({ select: l.tag }) }" data-link="layout" title="Select the item in the 3D layout">3D</RouterLink>
              </span>
            </td>
            <td class="status">
              <span class="badge" :class="STATUS_CHIPS[costStatus(l)].badge" :title="STATUS_CHIPS[costStatus(l)].title">{{ l.status }}</span>
              <span v-if="l.notes" class="notes muted">{{ l.notes }}</span>
            </td>
            <td>{{ l.correlation ?? "" }}</td>
            <td class="num">{{ l.size !== null ? `${num(l.size)} ${l.unit}` : l.unit ? `– ${l.unit}` : "" }}</td>
            <td class="source">
              <details v-if="l.size_source">
                <summary>
                  {{ sourceShort(l.size_source) }}
                  <span v-if="sizeAssumed(l.size_source)" class="badge warning">{{ l.size_source.startsWith("draft ") ? "draft" : "ASSUMED" }}</span>
                </summary>
                <p class="provenance">{{ l.size_source }}</p>
              </details>
            </td>
            <td class="num">{{ wholeMoney(l.cp0_base) }}</td>
            <td class="num">{{ num(l.fp) }}</td>
            <td class="num">{{ num(l.fm) }}</td>
            <td class="num">{{ num(l.fbm) }}</td>
            <td class="num">{{ wholeMoney(l.purchased) }}</td>
            <td class="num">{{ wholeMoney(l.bare_module) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <section v-if="estimate.own_costs.length" class="own" aria-label="Own costs">
      <h2>Project costs <span class="muted">from estimate/cost-basis.yaml, in their own currency and year, not in the totals</span></h2>
      <div class="table-wrap">
        <table class="data">
          <thead>
            <tr><th>tag</th><th class="num">cost</th><th>year</th><th>status</th><th>source</th></tr>
          </thead>
          <tbody>
            <tr v-for="o in estimate.own_costs" :key="o.tag">
              <td>{{ o.tag }}</td>
              <td class="num">{{ wholeMoney(o.cost, o.currency) }}</td>
              <td>{{ o.year }}</td>
              <td>{{ o.status }}</td>
              <td class="muted">{{ o.source }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="estimate.findings.length" class="findings" aria-label="Equipment findings">
      <h2>Findings <span class="muted">{{ estimate.findings.length }}</span></h2>
      <ul>
        <li v-for="(f, i) in estimate.findings" :key="i" :data-rule="f.rule">
          <span class="badge" :class="f.level">{{ f.level }}</span>
          <code class="rule">{{ f.rule.replace(/^cheme\./, "") }}</code>
          {{ f.message }}
          <span v-if="f.hint" class="muted finding-hint">{{ f.hint }}</span>
          <RouterLink class="file" :to="{ name: 'file', params: { path: pathSegments(f.file) }, query: withRev(f.line ? { line: String(f.line) } : {}) }">{{ f.file }}</RouterLink>
        </li>
      </ul>
    </section>
  </section>
</template>

<style scoped>
.hint {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
}
.index-source {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.notice {
  margin: 0 0 var(--space-3);
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: var(--space-2);
  margin-bottom: var(--space-2);
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
.card-value.accuracy {
  font-size: var(--text);
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
}
.chip {
  border: 1px solid transparent;
  cursor: pointer;
  font: inherit;
  font-size: 11.5px;
  font-weight: 600;
}
.chip[aria-pressed="true"] {
  border-color: currentColor;
}
.chip.off {
  opacity: 0.5;
}
.filter {
  min-width: 220px;
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--fg);
  font: inherit;
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
.lines td {
  font-size: var(--text-sm);
  vertical-align: top;
}
.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.tag-cell {
  white-space: nowrap;
}
.tag-cell .type {
  display: block;
  font-size: 11.5px;
}
.tag-cell .links {
  display: flex;
  gap: var(--space-2);
  font-size: 11.5px;
}
.source {
  min-width: 160px;
  max-width: 280px;
}
.source summary {
  cursor: pointer;
  font-weight: normal;
}
.provenance {
  margin: var(--space-1) 0 0;
  color: var(--fg-muted);
  overflow-wrap: anywhere;
}
.status {
  min-width: 200px;
  max-width: 320px;
}
.status .notes {
  display: block;
  font-size: 11.5px;
  margin-top: 2px;
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
.findings .finding-hint {
  display: block;
  margin-left: var(--space-4);
  font-size: 11.5px;
}
.findings .file {
  margin-left: var(--space-2);
  font-size: var(--text-sm);
}
@media (max-width: 700px) {
  .filter {
    min-width: 0;
    width: 100%;
  }
}
</style>
