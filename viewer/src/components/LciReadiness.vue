<script setup lang="ts">
/**
 * The LCI readiness of the plant's dataset: whether `lca/dataset.yaml` balances,
 * how good its data is, which documentation it lacks and which emission sources and consumables
 * are not yet covered, each linked to the file and line core names. Core computes all of it
 * (`/api/lca`: `balance`, `data_quality`, `water`, the findings); the pedigree per exchange is
 * read from the dataset core wrote. Hidden for a server that reports none of it.
 */
import { computed } from "vue";
import { api, type Finding, type LcaReport } from "@/api";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { pathSegments } from "@/lib/format";
import { impactText, shareText } from "@/lib/lca";
import {
  BALANCE_REQUIREMENTS,
  DATASET_FILE,
  PEDIGREE_INDICATORS,
  TOPIC_TITLES,
  balanceState,
  exchangeLines,
  hasReadiness,
  missingMetadata,
  pedigreeRows,
  readinessFindings,
  relativeText,
  stateClass,
  stateText,
  weakScore,
  type ReadinessTopic,
} from "@/lib/lciReadiness";

const props = defineProps<{ report: LcaReport }>();
const { rev, withRev } = useRev();

const shown = computed(() => hasReadiness(props.report));
const balance = computed(() => props.report.balance);
const quality = computed(() => props.report.data_quality);
const water = computed(() => props.report.water);
const found = computed(() => readinessFindings(props.report));
const metadata = computed(() => missingMetadata(props.report));
const listed: ReadinessTopic[] = ["emissions", "consumables", "documentation", "balance"];

/** Mass first, then each element, as core reports them. */
const closures = computed(() => {
  const b = balance.value;
  if (!b) return [];
  const rows = b.mass ? [{ name: "mass", ...b.mass }] : [];
  for (const [element, c] of Object.entries(b.elements ?? {})) rows.push({ name: element, unit: "kg", ...c });
  return rows;
});
const excluded = computed(() => Object.entries(balance.value?.excluded ?? {}));
const noComposition = computed(() => Object.entries(balance.value?.no_composition ?? {}));
const cutoff = computed(() => Object.entries(balance.value?.cutoff ?? {}));

// Whether the plant has a dataset: core reports `balance: null` without one (an older core
// leaves `balance` out, and the dataset may be there).
const hasDataset = computed(() => balance.value !== null);

// The dataset core wrote: each exchange's line (from its text) and the pedigree per exchange
// (from its data), read independently so one failing does not drop the other.
const dataset = useAsync(
  async (signal) => {
    if (!shown.value || !hasDataset.value) return null;
    const [doc, text] = await Promise.all([
      api.yaml(DATASET_FILE, rev.value, signal).catch((e: unknown) => e instanceof Error ? e : new Error(String(e))),
      api.file(DATASET_FILE, rev.value, signal).catch(() => null),
    ]);
    const lines = exchangeLines(text);
    if (doc instanceof Error) return { rows: [], lines, problem: doc.message };
    return { rows: pedigreeRows(doc.data, lines), lines, problem: null };
  },
  [rev, shown, hasDataset],
);
const exchanges = computed(() => dataset.data.value?.rows ?? []);
const lineOf = computed(() => dataset.data.value?.lines ?? new Map<string, number>());
const pedigreeProblem = computed(() => dataset.data.value?.problem ?? dataset.error.value);

const INDICATORS: ["TeR" | "GeR" | "TiR", string][] = [
  ["TeR", "technological"],
  ["GeR", "geographical"],
  ["TiR", "temporal"],
];

function fileLink(file: string, line?: number | null) {
  return { name: "file", params: { path: pathSegments(file) }, query: withRev(line ? { line: String(line) } : {}) };
}
function findingLink(f: Finding) {
  return fileLink(f.file, f.line);
}
</script>

<template>
  <section v-if="shown" class="readiness" aria-label="LCI readiness" data-readiness>
    <h2>
      LCI readiness
      <span class="muted">
        how far <RouterLink v-if="hasDataset" :to="fileLink(DATASET_FILE)">{{ DATASET_FILE }}</RouterLink><code v-else>{{ DATASET_FILE }}</code>
        <template v-if="balance?.dataset"> ({{ balance.dataset }})</template> is from publication, as core reports it
      </span>
    </h2>

    <div class="cards">
      <div class="card" data-readiness-card="balance">
        <span class="card-title">Balance</span>
        <span v-if="balance" class="states">
          <span v-for="r in BALANCE_REQUIREMENTS" :key="r.id" class="badge" :class="stateClass(balanceState(balance, r.id))" :data-balance-state="r.id">{{ r.label }}: {{ stateText(balanceState(balance, r.id)) }}</span>
        </span>
        <strong v-else-if="balance === null" class="card-value">no dataset</strong>
        <strong v-else class="card-value" data-balance-unknown>not assessed</strong>
      </div>
      <div class="card" data-readiness-card="dqr">
        <span class="card-title">Data quality (DQR, 1 best .. 5)</span>
        <template v-if="quality">
          <strong class="card-value">{{ quality.dqr.toFixed(2) }}</strong>
          <span class="muted">weakest: {{ quality.weakest }}</span>
        </template>
        <strong v-else class="card-value">not rated</strong>
      </div>
      <div class="card" data-readiness-card="documentation">
        <span class="card-title">Publication minimum</span>
        <strong class="card-value">{{ metadata.fields.length ? `${metadata.fields.length} missing` : "complete" }}</strong>
      </div>
      <div v-if="found.emissions.length" class="card" data-readiness-card="emissions">
        <span class="card-title">Emission sources without an estimate</span>
        <strong class="card-value">{{ found.emissions.reduce((n, f) => n + f.ids.length, 0) }}</strong>
      </div>
      <div v-if="water !== undefined" class="card" data-readiness-card="water">
        <span class="card-title">Water</span>
        <template v-if="water">
          <strong class="card-value">{{ impactText(water.consumption) }} <span class="unit">{{ water.unit }}</span></strong>
          <span class="muted">consumed per {{ water.basis }}</span>
        </template>
        <strong v-else class="card-value">no water flow</strong>
      </div>
    </div>

    <h3>
      Balance
      <span class="muted">
        of <RouterLink v-if="hasDataset" :to="fileLink(DATASET_FILE)" data-source="balance">{{ DATASET_FILE }}</RouterLink><code v-else>{{ DATASET_FILE }}</code><template v-if="balance">, per {{ balance.basis }}, tolerance {{ shareText(balance.tolerance) }} ({{ balance.tolerance_basis }})</template>
      </span>
    </h3>
    <p v-if="balance === undefined" class="muted" data-balance-not-assessed>
      Not assessed: this server's core predates the balance gates and does not report the dataset's balance. A current core reports the closure here, and
      <code>cheme assess lca --write</code> records it in <RouterLink :to="fileLink('lca/manifest.json')">lca/manifest.json</RouterLink> (<code>balance</code>).
    </p>
    <p v-else-if="balance === null" class="muted">No LCI dataset to balance.</p>
    <template v-else>
      <div class="table-wrap">
        <table class="data" aria-label="Closure">
          <thead>
            <tr><th>quantity</th><th class="num">in</th><th class="num">out</th><th class="num">residual</th><th class="num">relative</th><th>status</th></tr>
          </thead>
          <tbody>
            <tr v-for="c in closures" :key="c.name" :data-closure="c.name">
              <td>{{ c.name }}</td>
              <td class="num">{{ impactText(c.in) }} {{ c.unit }}</td>
              <td class="num">{{ impactText(c.out) }} {{ c.unit }}</td>
              <td class="num">{{ impactText(c.residual) }} {{ c.unit }}</td>
              <td class="num">{{ relativeText(c.relative) }}</td>
              <td><span class="badge" :class="c.closed ? 'pass' : 'warning'">{{ c.closed ? "closed" : "open" }}</span></td>
            </tr>
            <tr v-if="balance.carbon" data-closure="carbon">
              <td>
                carbon by origin
                <span class="muted">in {{ Object.entries(balance.carbon.inputs).filter(([, v]) => v).map(([k, v]) => `${k} ${impactText(v)}`).join(", ") || "none" }}; out {{ Object.entries(balance.carbon.outputs).map(([k, v]) => `${k} ${impactText(v)}`).join(", ") || "none" }}</span>
              </td>
              <td class="num">{{ impactText(balance.carbon.in) }} {{ balance.carbon.unit }}</td>
              <td class="num">{{ impactText(balance.carbon.out) }} {{ balance.carbon.unit }}</td>
              <td class="num">{{ impactText(balance.carbon.residual) }} {{ balance.carbon.unit }}</td>
              <td class="num">{{ relativeText(balance.carbon.relative) }}</td>
              <td>
                <span class="badge" :class="balance.carbon.closed ? 'pass' : 'warning'">{{ balance.carbon.closed ? "closed" : "open" }}</span>
                <span v-if="balance.carbon.mismatched.length" class="muted"> origin mismatch: {{ balance.carbon.mismatched.join(", ") }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="muted hint" data-energy>
        Energy: <template v-if="balance.energy.closure !== null">out / in {{ shareText(balance.energy.closure) }}</template><template v-else>no energy enters that core can classify</template><template v-if="balance.energy.unclassified.length">; carrier unknown, not counted: {{ balance.energy.unclassified.join(", ") }}</template>.
      </p>
      <ul v-if="balance.problems.length && !found.balance.length" class="problems" data-balance-problems>
        <li v-for="p in balance.problems" :key="p">{{ p }}</li>
      </ul>
      <p v-if="noComposition.length" class="hint" data-no-composition>
        No composition (the element balance cannot read them):
        <template v-for="([key, why], i) in noComposition" :key="key"><template v-if="i">, </template><RouterLink :to="fileLink(DATASET_FILE, lineOf.get(key))"><code>{{ key }}</code></RouterLink> <span class="muted">({{ why }})</span></template>
      </p>
      <details v-if="excluded.length" class="hint" data-excluded>
        <summary>{{ excluded.length }} {{ excluded.length === 1 ? "exchange" : "exchanges" }} outside the mass and element balances</summary>
        <ul>
          <li v-for="[key, why] in excluded" :key="key">
            <RouterLink :to="fileLink(DATASET_FILE, lineOf.get(key))"><code>{{ key }}</code></RouterLink> <span class="muted">{{ why }}</span>
          </li>
        </ul>
      </details>
      <details v-if="cutoff.length" class="hint" data-cutoff>
        <summary>{{ cutoff.length }} {{ cutoff.length === 1 ? "cut-off flow" : "cut-off flows" }}, listed beside the balance and not counted in it</summary>
        <ul>
          <li v-for="[key, flow] in cutoff" :key="key" :data-cutoff-flow="key">
            <RouterLink :to="fileLink(DATASET_FILE, lineOf.get(key))"><code>{{ key }}</code></RouterLink>
            <span class="muted"> {{ flow.direction }}<template v-if="flow.amount !== null">, {{ impactText(flow.amount) }} {{ flow.unit }}</template><template v-else>, amount not given</template></span>
          </li>
        </ul>
      </details>
    </template>

    <h3>
      Data quality
      <span class="muted">
        from the pedigree in <RouterLink v-if="hasDataset" :to="fileLink(DATASET_FILE)" data-source="dqr">{{ DATASET_FILE }}</RouterLink><code v-else>{{ DATASET_FILE }}</code><template v-if="quality">; {{ quality.exchanges }} exchanges rated, {{ quality.weighted ? `weighted by their contribution to ${quality.basis}` : "unweighted (a simplification)" }}</template>
      </span>
    </h3>
    <template v-if="quality">
      <dl class="meta" data-dqr>
        <dt>DQR</dt>
        <dd>{{ quality.dqr.toFixed(2) }} <span class="muted">(TeR + GeR + TiR) / 3</span></dd>
        <template v-for="[id, name] in INDICATORS" :key="id">
          <dt>{{ id }}</dt>
          <dd :class="{ weakest: quality.weakest === id }" :data-indicator="id">{{ quality[id].toFixed(2) }} <span class="muted">{{ name }}</span><span v-if="quality.weakest === id" class="badge warning">weakest</span></dd>
        </template>
        <dt>P, C</dt>
        <dd>{{ quality.P.toFixed(2) }}, {{ quality.C.toFixed(2) }} <span class="muted">(PEF DQR {{ quality.dqr_pef.toFixed(2) }})</span></dd>
        <dt>primary data</dt>
        <dd>{{ shareText(quality.primary_share) }}</dd>
      </dl>
      <details v-if="exchanges.length" class="pedigree" data-pedigree>
        <summary>Pedigree per exchange <span class="muted">({{ exchanges.length }}, from {{ DATASET_FILE }}; 4 and 5 highlighted)</span></summary>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr>
                <th>exchange</th>
                <th>type</th>
                <th v-for="name in PEDIGREE_INDICATORS" :key="name" class="num">{{ name }}</th>
                <th>basis</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in exchanges" :key="r.key" :data-pedigree-row="r.key">
                <td><RouterLink :to="fileLink(DATASET_FILE, r.line)"><code>{{ r.key }}</code></RouterLink> <span class="muted">{{ r.title }}</span></td>
                <td>{{ r.type }}</td>
                <td v-for="(s, i) in r.scores" :key="i" class="num" :class="{ weak: weakScore(s) }">{{ s }}</td>
                <td class="muted">{{ r.basis }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>
      <p v-else-if="pedigreeProblem" class="muted hint" data-pedigree-problem>The pedigree per exchange is not available: {{ pedigreeProblem }}</p>
    </template>
    <p v-else class="muted">Not rated: no exchange of the dataset carries a pedigree.</p>

    <h3>Documentation <span class="muted">the publication minimum</span></h3>
    <p v-if="metadata.fields.length" data-missing-metadata>
      Missing:
      <span v-for="field in metadata.fields" :key="field" class="badge warning" :data-missing="field">{{ field }}</span>
      <RouterLink v-if="metadata.finding" class="file" :to="findingLink(metadata.finding)">{{ metadata.finding.file }}{{ metadata.finding.line ? `:${metadata.finding.line}` : "" }}</RouterLink>
    </p>
    <p v-else class="muted">The dataset gives the publication minimum.</p>
    <p v-if="metadata.finding?.hint" class="muted hint">{{ metadata.finding.hint }}</p>

    <template v-for="topic in listed" :key="topic">
      <div v-if="found[topic].filter((f) => f !== metadata.finding).length" class="findings" :data-topic="topic">
        <h3>{{ TOPIC_TITLES[topic] }}</h3>
        <ul>
          <li v-for="(f, i) in found[topic].filter((x) => x !== metadata.finding)" :key="i">
            <span class="badge" :class="f.level">{{ f.level }}</span>
            <code class="rule">{{ f.rule.replace(/^cheme\./, "") }}</code>
            {{ f.message }}
            <RouterLink class="file" :to="findingLink(f)">{{ f.file }}{{ f.line ? `:${f.line}` : "" }}</RouterLink>
          </li>
        </ul>
      </div>
    </template>

    <template v-if="water">
      <h3>Water <span class="muted">m3 per {{ water.basis }}</span></h3>
      <dl class="meta" data-water>
        <dt>withdrawal</dt>
        <dd>{{ impactText(water.withdrawal) }} {{ water.unit }}</dd>
        <dt>returned</dt>
        <dd>{{ impactText(water.returned) }} {{ water.unit }}</dd>
        <dt>evaporated</dt>
        <dd>{{ impactText(water.evaporated) }} {{ water.unit }}</dd>
        <dt>consumption</dt>
        <dd>{{ impactText(water.consumption) }} {{ water.unit }} <span class="muted">withdrawal minus returned</span></dd>
      </dl>
    </template>
  </section>
</template>

<style scoped>
.readiness {
  padding: var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  margin-bottom: var(--space-4);
}
h2 {
  font-size: var(--text);
  margin: 0 0 var(--space-2);
  display: flex;
  gap: var(--space-2);
  align-items: baseline;
  flex-wrap: wrap;
}
h2 .muted,
h3 .muted {
  font-weight: normal;
  font-size: var(--text-sm);
}
h3 {
  font-size: var(--text-sm);
  margin: var(--space-3) 0 var(--space-1);
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: var(--space-2);
}
.card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg);
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
.states {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.meta {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 2px var(--space-3);
  margin: 0 0 var(--space-2);
  font-size: var(--text-sm);
}
.meta dt {
  color: var(--fg-muted);
}
.meta dd {
  margin: 0;
}
.meta .badge {
  margin-left: var(--space-1);
}
.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
table td {
  font-size: var(--text-sm);
}
.weak,
.weakest {
  color: var(--bad);
  font-weight: 600;
}
.hint,
.problems {
  margin: var(--space-1) 0 0;
  font-size: var(--text-sm);
}
.problems {
  padding-left: 1.2em;
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
.file {
  margin-left: var(--space-2);
  font-size: var(--text-sm);
}
[data-missing-metadata] .badge {
  margin-right: 4px;
}
summary {
  cursor: pointer;
}
</style>
