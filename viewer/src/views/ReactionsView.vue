<script setup lang="ts">
/**
 * The reactions of the plant (`GET /api/reactions`): each reaction of `process/reactions.yaml`
 * with what the flowsheet says about it, the rows of `cheme process reactors` and the reactive
 * balances with their findings; the kinetics: each rate law with its parameters, provenance and
 * k(T), the fixed beds along their catalyst mass (peak, reference temperatures, the
 * profile as a table, the bed's row of a recorded simulation run, or why core could not solve
 * it), and the catalysts of
 * `process/catalysts.yaml` linked to the reactions they catalyse; each mechanism
 * analysed at its reactor's outlet (coverages, TOF, degree of rate control) and the kinetic data
 * of `experiments/kinetics/` with their default fits (`GET /api/kinetics`).
 */
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, ApiError, type KineticsView, type RateLaw, type Reaction, type ReactionMechanism, type ReactionPlace, type ReactionsView, type ReactorRow, type SimulationView } from "@/api";
import BedProfile from "@/components/BedProfile.vue";
import FindingsList from "@/components/FindingsList.vue";
import LineChart from "@/components/LineChart.vue";
import LoadState from "@/components/LoadState.vue";
import { store } from "@/store";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { refocusAfterLoad } from "@/lib/refocus";
import { pathSegments, shortRev } from "@/lib/format";
import { BALANCE_BADGE, PROVENANCE_SHORT, balanceDetail, formatNumber } from "@/lib/process";
import {
  EQUIPMENT_LIST,
  REACTIONS_FILE,
  approachOf,
  arrheniusText,
  catalystAnchor,
  catalystOf,
  changeText,
  elementBadge,
  equationText,
  equipmentSheets,
  extentOf,
  heatText,
  kineticsOf,
  lnText,
  nodePidLink,
  ordersText,
  rangeText,
  rateFormText,
  reactionAnchor,
} from "@/lib/reactions";
import { bedRunRecord, declaredBed, fixedBeds } from "@/lib/fixedBed";
import { coverageBars, fitRows, fugacityText, masi, parameterName, parameterText, pressuresText, rateControlBars, rateDeterminingStep, rateUnit, sig, stepEquation, worstDeviation } from "@/lib/catalysis";

const route = useRoute();
const router = useRouter();
const { rev, withRev } = useRev();
const caseId = computed(() => (typeof route.query.case === "string" ? route.query.case : ""));

/** The reactions at `rev` for the case, or null without `process/reactions.yaml` (a 404). */
const report = useAsync<ReactionsView | null>(async (signal) => {
  try {
    return await api.reactions({ case: caseId.value, rev: rev.value }, signal);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}, [caseId, rev]);
const data = computed(() => report.data.value ?? null);
/**
 * The kinetic data and their fits at `rev` (a 404: none there, or an older server). Asked at every
 * rev: the repo's `has_kinetic_data` describes the working tree, and loads after a deep link.
 */
const kineticData = useAsync<KineticsView | null>(
  (signal) => api.kinetics(rev.value, signal).catch((error) => (error instanceof ApiError && error.status === 404 ? null : Promise.reject(error))),
  rev,
);
const dataFiles = computed(() => kineticData.data.value?.files ?? []);
const missing = computed(() => !report.loading.value && !report.error.value && report.data.value === null);

// Where a reactor is drawn: its flowsheet node's links (the stream table's nodes), a tag's sheet
// from the equipment list when a link names none. Neither is needed for the page: failures are empty.
const table = useAsync((signal) => api.streams({ case: caseId.value, rev: rev.value }, signal).catch(() => null), [caseId, rev]);
const equipment = useAsync((signal) => api.yaml(EQUIPMENT_LIST, rev.value, signal).then((doc) => doc.data).catch(() => null), rev);
const tagSheets = computed(() => equipmentSheets(equipment.data.value));
function pidLink(node: string) {
  const link = nodePidLink(node, table.data.value?.nodes ?? [], store.repo?.sheets ?? [], tagSheets.value);
  return link ? { name: "pid", params: { path: pathSegments(link.file) }, query: withRev(link.select ? { select: link.select } : {}) } : null;
}

const reactions = computed(() => data.value?.reactions ?? []);
const reactors = computed(() => data.value?.reactors ?? []);
const balances = computed(() => data.value?.balance.balances ?? []);
const findings = computed(() => data.value?.balance.findings ?? []);
const unbalanced = computed(() => reactions.value.filter((r) => r.element_balance.balanced === false).length);
const titles = computed(() => new Map(reactions.value.map((r) => [r.id, r.title])));
const kinetics = computed(() => kineticsOf(data.value));
const catalysts = computed(() => kinetics.value.catalysts);
const withRate = computed(() => reactions.value.filter((r): r is Reaction & { rate: RateLaw } => Boolean(r.rate)));
const withMechanism = computed(() => reactions.value.filter((r): r is Reaction & { mechanism: ReactionMechanism } => Boolean(r.mechanism)));
const beds = computed(() => fixedBeds(reactors.value));
/**
 * The recorded simulation run at `rev` for the case, for the beds' rows (a coupled kinetic
 * reactor keeps its peak and pressure drop): asked only when the page has a fixed bed; a 404 (no
 * process/simulation.yaml, an older server, a snapshot without it) or a failure is none.
 */
const simulation = useAsync<SimulationView | null>(
  (signal) =>
    beds.value.length
      ? api.simulation({ case: caseId.value, rev: rev.value }, signal).catch((error) => (error instanceof ApiError && error.status === 404 ? null : Promise.reject(error)))
      : Promise.resolve(null),
  [caseId, rev, () => beds.value.length > 0],
);
const bedSource = computed(() => (data.value?.rev ? `commit ${shortRev(data.value.rev)}` : rev.value ? shortRev(rev.value) : "the working tree"));
const bedCsvName = (node: string) => `bed-${node}-${data.value?.case ?? "case"}${rev.value ? `-${shortRev(rev.value)}` : ""}.csv`;
const catalystFindings = computed(() => kinetics.value.findings);
const kPoints = (r: Reaction) => (r.rate_law?.k_profile ?? []).map((p) => [p.temperature_K, p.k] as [number, number]);
const provTitle = (x: { provenance?: string | undefined; source?: string | undefined }) => [x.provenance, x.source].filter(Boolean).join(": ");
/** Scroll to a catalyst's card or a reaction's row and mark it (no URL hash: a snapshot's router uses it). */
const focused = ref("");
function focus(id: string): void {
  focused.value = id;
  document.getElementById(id)?.scrollIntoView({ block: "center", behavior: "smooth" });
}
/** The bed as the flowsheet declares it: `catalyst_mass 40000 kg, diameter 3 m, adiabatic`. */
const BED_UNITS: Record<string, string> = { catalyst_mass: "kg", volume: "m³", diameter: "m", length: "m", coolant_temperature: "K", heat_transfer_coefficient: "W/(m² K)", viscosity: "Pa s" };
function bedText(bed: Record<string, unknown> | null): string {
  if (!bed) return "";
  return Object.entries(bed)
    .filter(([k, v]) => v !== null && v !== undefined && k !== "provenance" && k !== "source" && !(k === "tubes" && v === 1))
    .map(([k, v]) => (k === "heat" ? String(v) : `${k.replace(/_/g, " ")} ${typeof v === "number" ? formatNumber(v) : String(v)}${BED_UNITS[k] ? ` ${BED_UNITS[k]}` : ""}`))
    .join(", ");
}

// The page (and its case select) is redrawn once the picked case has loaded.
const keepCaseFocus = refocusAfterLoad('select[aria-label="Case"]', report, rev);
function setCase(id: string): void {
  keepCaseFocus();
  void router.replace({ query: { ...route.query, case: id || undefined } });
}
const kelvin = (v: number | null) => (v === null ? "" : `${formatNumber(Number(v.toFixed(2)))} K`);
const kpa = (v: number | null) => (v === null ? "" : `${formatNumber(Number(v.toFixed(1)))} kPa`);
const extentText = (v: number | null) => (v === null ? "" : `${formatNumber(Number(v.toFixed(3)))} kmol/h`);
const dutyText = (r: ReactorRow) => (r.duty_kW === null ? "" : `${formatNumber(Number(r.duty_kW.toFixed(1)))} kW`);
/** `equilibrium, ΔT 20 K` or `conversion, X 0.3 (flowsheet R1)`. */
const placeText = (p: ReactionPlace) =>
  [p.model, p.approach_K ? `ΔT ${formatNumber(p.approach_K)} K` : "", p.conversion ? `X ${formatNumber(p.conversion.value)} (${p.conversion.from})` : ""].filter(Boolean).join(", ");
const fileLink = (path: string) => ({ name: "file", params: { path: pathSegments(path) }, query: withRev() });
</script>

<template>
  <div class="page reactions-page">
    <h1>
      Reactions
      <small>{{ REACTIONS_FILE }}{{ rev ? ` at ${shortRev(rev)}` : " in the working tree" }}</small>
      <span v-if="unbalanced" class="badge fail">{{ unbalanced }} unbalanced</span>
    </h1>

    <LoadState :loading="report.loading.value && !data" :error="report.error.value" @retry="report.reload" />
    <div v-if="missing" class="notice" data-reactions-missing>
      <p><strong>No reactions{{ rev ? ` at ${shortRev(rev)}` : "" }}.</strong></p>
      <p class="muted">
        The page shows <code>{{ REACTIONS_FILE }}</code> (schema <code>cheme schema reactions</code>) with the reactors of the flowsheet that run each reaction, as
        <code>cheme process reactors</code> reports them. This server or snapshot has none to show.
      </p>
    </div>

    <template v-if="data">
      <div class="toolbar">
        <label class="field">
          Case
          <select :value="data.case" aria-label="Case" :disabled="data.cases.length < 2" @change="setCase(($event.target as HTMLSelectElement).value)">
            <option v-for="c in data.cases" :key="c" :value="c">{{ c }}</option>
          </select>
        </label>
        <span class="spacer" />
        <RouterLink class="btn" :to="fileLink(data.file)">Source</RouterLink>
        <RouterLink class="btn" :to="{ name: 'streams', query: withRev(caseId ? { case: caseId } : {}) }">Stream table</RouterLink>
        <RouterLink class="btn" :to="{ name: 'library', query: withRev() }" title="Industrial processes with their components, reactions and catalysts (cheme chemistry library)">Reaction library</RouterLink>
      </div>

      <h2>Reactions <span class="muted count">{{ reactions.length }}</span></h2>
      <p v-if="!reactions.length" class="muted">No reactions declared.</p>
      <div v-else class="table-wrap">
        <table class="data reaction-table" aria-label="Reactions">
          <thead>
            <tr>
              <th>Reaction</th>
              <th>Equation</th>
              <th>Type</th>
              <th>Phase</th>
              <th>Key</th>
              <th>Conversion / K</th>
              <th>ΔH</th>
              <th>Catalyst</th>
              <th>Runs in</th>
              <th>Elements</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in reactions" :id="reactionAnchor(r.id)" :key="r.id" :data-reaction="r.id" :class="{ error: r.element_balance.balanced === false, focused: focused === reactionAnchor(r.id) }">
              <td class="id-cell">
                <strong>{{ r.id }}</strong>
                <span v-if="r.title" class="muted title">{{ r.title }}</span>
                <details v-if="r.sources.length" class="sources">
                  <summary>{{ r.sources.length }} source{{ r.sources.length === 1 ? "" : "s" }}</summary>
                  <ul>
                    <li v-for="(src, i) in r.sources" :key="i">{{ src }}</li>
                  </ul>
                </details>
              </td>
              <td class="mono equation" data-equation>{{ equationText(r) }}</td>
              <td data-type>{{ r.type ?? "" }}</td>
              <td>{{ r.phase ?? "" }}<span v-if="r.reversible" class="muted"> reversible</span></td>
              <td class="mono">{{ r.key_component ?? "" }}</td>
              <td data-extent>
                <template v-if="extentOf(r).text">
                  {{ extentOf(r).text }}
                  <span v-if="extentOf(r).provenance" class="prov" :class="extentOf(r).provenance!" :title="[extentOf(r).provenance, extentOf(r).source].filter(Boolean).join(': ')">{{ PROVENANCE_SHORT[extentOf(r).provenance!] }}</span>
                  <span v-if="extentOf(r).source" class="muted source">{{ extentOf(r).source }}</span>
                </template>
              </td>
              <td class="heat" data-heat>
                <template v-if="r.heat_of_reaction">
                  {{ heatText(r.heat_of_reaction) }}
                  <span class="prov" :class="r.heat_of_reaction.provenance" :title="[r.heat_of_reaction.provenance, r.heat_of_reaction.source].filter(Boolean).join(': ')">{{ PROVENANCE_SHORT[r.heat_of_reaction.provenance] }}</span>
                  <span v-if="r.heat_of_reaction.source" class="muted source">{{ r.heat_of_reaction.source }}</span>
                </template>
              </td>
              <td class="catalyst" data-catalyst>
                <template v-if="catalystOf(r, catalysts)">
                  <a v-if="catalystOf(r, catalysts)!.entry" href="#" data-link="catalyst" :title="`Show catalyst ${catalystOf(r, catalysts)!.id}`" @click.prevent="focus(catalystAnchor(catalystOf(r, catalysts)!.id))">{{ catalystOf(r, catalysts)!.id }}</a>
                  <span v-else :title="kinetics.file ? 'Not declared in process/catalysts.yaml' : 'No process/catalysts.yaml'">{{ catalystOf(r, catalysts)!.id }}</span>
                </template>
                <div v-if="r.rate" class="small"><a href="#" data-link="rate-law" @click.prevent="focus(`rate-${r.id}`)">{{ r.rate.form === "lhhw" ? "LHHW" : "power law" }}</a></div>
              </td>
              <td class="places">
                <div v-for="p in r.units" :key="p.unit" :data-place="p.unit">
                  <strong>{{ p.unit }}</strong> <span class="muted">{{ placeText(p) }}</span>
                </div>
                <span v-if="!r.units.length" class="muted">none</span>
              </td>
              <td>
                <span class="badge" :class="elementBadge(r).badge" :title="elementBadge(r).title" data-elements>{{ elementBadge(r).label }}</span>
                <div v-if="r.element_balance.balanced === false" class="err small">{{ changeText(r.element_balance.change) }}</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <template v-if="withRate.length">
        <h2>Rate laws <span class="muted count">{{ withRate.length }}</span></h2>
        <div class="cards">
          <article v-for="r in withRate" :id="`rate-${r.id}`" :key="r.id" class="card rate-card" :class="{ focused: focused === `rate-${r.id}` }" :data-rate-law="r.id" :aria-label="`Rate law of ${r.id}`">
            <header>
              <strong>{{ r.id }}</strong> <span class="muted">{{ r.title }}</span>
              <span class="prov" :class="r.rate.provenance" :title="provTitle(r.rate)" data-prov>{{ PROVENANCE_SHORT[r.rate.provenance] }}</span>
            </header>
            <p class="mono expression" data-expression>{{ r.rate_law?.expression }}</p>
            <p class="mono muted small">{{ r.rate_law?.k_expression }}</p>
            <dl class="params">
              <dt>Form</dt>
              <dd data-form>{{ rateFormText(r.rate) }}<template v-if="r.rate.reverse === 'equilibrium'">, to equilibrium (1 − Q/K)</template></dd>
              <dt>k</dt>
              <dd data-k>{{ arrheniusText(r.rate.k, r.rate_law?.k_unit) }}</dd>
              <dt>Orders</dt>
              <dd data-orders>{{ ordersText(r.rate.orders) || "none" }}</dd>
              <template v-if="r.rate.adsorption.length">
                <dt>Adsorption</dt>
                <dd data-adsorption>
                  <div v-for="(a, i) in r.rate.adsorption" :key="i">K{{ i + 1 }}: A {{ formatNumber(a.A) }}, ΔH {{ formatNumber(a.dH) }} kJ/kmol<template v-if="Object.keys(a.exponents).length">; {{ ordersText(a.exponents) }}</template></div>
                  <div v-if="r.rate.power !== 1" class="muted">power {{ formatNumber(r.rate.power) }}</div>
                </dd>
              </template>
              <dt>Rate</dt>
              <dd>{{ r.rate_law?.rate_unit }}</dd>
              <dt>Valid</dt>
              <dd data-range>{{ rangeText(r.rate.temperature_range, "K") || "no range given" }}</dd>
              <dt>Catalyst</dt>
              <dd>
                <template v-if="catalystOf(r, catalysts)">
                  <a v-if="catalystOf(r, catalysts)!.entry" href="#" data-link="catalyst" @click.prevent="focus(catalystAnchor(catalystOf(r, catalysts)!.id))">{{ catalystOf(r, catalysts)!.id }}</a>
                  <span v-else>{{ catalystOf(r, catalysts)!.id }} <span class="warn small">not declared</span></span>
                </template>
                <span v-else class="muted">none</span>
              </dd>
              <dt>Source</dt>
              <dd class="source-text" data-source>{{ r.rate.source || "none given" }}</dd>
            </dl>
            <LineChart
              v-if="kPoints(r).length"
              :points="kPoints(r)"
              x-label="T (K)"
              y-label="k"
              log
              :label="`k(T) of ${r.id} over its ${r.rate_law?.k_profile_from}`"
              :caption="`k in ${r.rate_law?.k_unit}, over the ${r.rate_law?.k_profile_from === 'temperature_range' ? 'rate law\'s temperature range' : 'catalyst\'s temperature window'}`"
            />
          </article>
        </div>
      </template>

      <template v-if="withMechanism.length">
        <h2>Mechanisms <span class="muted count">{{ withMechanism.length }}</span></h2>
        <div class="cards">
          <article v-for="r in withMechanism" :key="r.id" class="card" :data-mechanism="r.id">
            <header>
              <strong>{{ r.id }}</strong> <span class="muted">{{ r.mechanism.steps.length }} elementary steps on {{ r.mechanism.adsorbates.length }} adsorbates</span>
              <span class="prov" :class="r.mechanism.provenance" :title="provTitle(r.mechanism)">{{ PROVENANCE_SHORT[r.mechanism.provenance] }}</span>
            </header>
            <ol class="mono small steps">
              <li v-for="step in r.mechanism.steps" :key="step.id" :data-step-equation="step.id"><strong>{{ step.id }}</strong> {{ stepEquation(step) }}</li>
            </ol>
            <template v-if="r.microkinetics">
              <p v-if="r.microkinetics.missing" class="muted small" data-mk-missing>
                Not analysed<template v-if="r.microkinetics.conditions"> at {{ r.microkinetics.conditions.stream }}</template>: {{ r.microkinetics.missing }}
              </p>
              <div v-else class="microkinetics" data-microkinetics>
                <p class="small muted" data-mk-conditions>
                  At the outlet {{ r.microkinetics.conditions!.stream }} of <strong>{{ r.microkinetics.conditions!.unit }}</strong>: {{ kelvin(r.microkinetics.conditions!.temperature_K) }}, {{ pressuresText(r.microkinetics.conditions!.pressures_bar) }}
                </p>
                <dl class="params">
                  <dt>TOF</dt>
                  <dd data-tof>{{ sig(r.microkinetics.tof_per_s) }} 1/s<template v-if="r.microkinetics.product"> ({{ r.microkinetics.product }} per site)</template></dd>
                  <dt>Apparent Ea</dt>
                  <dd data-ea>{{ sig(r.microkinetics.apparent_activation_kJ_kmol) }} kJ/kmol</dd>
                  <dt>Orders</dt>
                  <dd data-mk-orders>{{ Object.entries(r.microkinetics.orders ?? {}).map(([n, a]) => `${n} ${sig(a, 3)}`).join(", ") || "none" }}</dd>
                  <template v-if="rateDeterminingStep(r.microkinetics) || masi(r.microkinetics)">
                    <dt>Reads</dt>
                    <dd data-mk-reading>
                      {{ [rateDeterminingStep(r.microkinetics) ? `${rateDeterminingStep(r.microkinetics)} controls the rate` : "", masi(r.microkinetics) ? `${masi(r.microkinetics)} covers most sites` : ""].filter(Boolean).join("; ") }}
                    </dd>
                  </template>
                </dl>
                <div class="bar-groups">
                  <div class="bars" :aria-label="`Coverages of ${r.id}`" data-coverages>
                    <div class="bars-title small muted">Coverage</div>
                    <div v-for="b in coverageBars(r.microkinetics.coverages)" :key="b.id" class="bar-row small" :data-coverage="b.id">
                      <span class="mono bar-label">{{ b.id }}</span>
                      <span class="track"><span class="fill" :style="{ width: `${b.width * 100}%` }" /></span>
                      <span class="bar-value">{{ b.text }}</span>
                    </div>
                  </div>
                  <div class="bars" :aria-label="`Degree of rate control of ${r.id}`" data-rate-control>
                    <div class="bars-title small muted" title="Campbell's degree of rate control: how much the rate rises with each step's rate constant (they sum to 1)">Degree of rate control</div>
                    <div v-for="b in rateControlBars(r.microkinetics.rate_control)" :key="b.id" class="bar-row small" :data-step="b.id">
                      <span class="mono bar-label">{{ b.id }}</span>
                      <span class="track"><span class="fill" :class="{ negative: b.value < 0 }" :style="{ width: `${b.width * 100}%` }" /></span>
                      <span class="bar-value">{{ b.text }}</span>
                    </div>
                  </div>
                </div>
                <p class="muted small">Mean-field steady state, as <code>cheme chemistry microkinetics</code> computes it.</p>
              </div>
            </template>
          </article>
        </div>
      </template>

      <h2>Reactors <span class="muted count">{{ reactors.length }}</span> <span class="muted small">(<code>cheme process reactors</code>, case {{ data.case }})</span></h2>
      <p v-if="!reactors.length" class="muted">No reactive block or step in the flowsheet.</p>
      <div v-else class="table-wrap">
        <table class="data reactor-table" aria-label="Reactors">
          <thead>
            <tr>
              <th>Node</th>
              <th>Model</th>
              <th>Balance</th>
              <th>T out</th>
              <th>P out</th>
              <th>Reaction</th>
              <th>Extent</th>
              <th title="ln(Q/K) at the outlet: 0 at equilibrium, negative short of it">ln(Q/K)</th>
              <th>Duty</th>
              <th>Missing</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="row in reactors" :key="row.node">
              <tr v-for="(rx, i) in row.reactions.length ? row.reactions : [null]" :key="`${row.node}-${rx?.id ?? i}`" :data-reactor="row.node" :class="{ first: i === 0 }">
                <template v-if="i === 0">
                  <td class="id-cell" :rowspan="Math.max(row.reactions.length, 1)">
                    <RouterLink v-if="pidLink(row.node)" :to="pidLink(row.node)!" data-link="pid" :title="`Open ${row.node} on its P&ID`"><strong>{{ row.node }}</strong></RouterLink>
                    <strong v-else>{{ row.node }}</strong>
                    <span class="faint kind">{{ row.kind }}</span>
                    <div class="mono small muted">{{ row.streams_in.join(", ") }} → {{ row.streams_out.join(", ") }}</div>
                  </td>
                  <td :rowspan="Math.max(row.reactions.length, 1)">
                    {{ [row.model, row.approach_K ? `ΔT ${formatNumber(row.approach_K)} K` : ""].filter(Boolean).join(", ") }}
                    <span v-if="fugacityText(row)" class="badge" title="The equilibrium uses Peng–Robinson fugacity coefficients, not the ideal gas" data-fugacity>{{ fugacityText(row) }}</span>
                  </td>
                  <td :rowspan="Math.max(row.reactions.length, 1)"><span class="badge" :class="BALANCE_BADGE[row.balance as keyof typeof BALANCE_BADGE] ?? ''">{{ row.balance }}</span></td>
                  <td class="num" :rowspan="Math.max(row.reactions.length, 1)" data-t-out>{{ kelvin(row.temperature_out_K) }}</td>
                  <td class="num" :rowspan="Math.max(row.reactions.length, 1)">{{ kpa(row.pressure_out_kPa) }}</td>
                </template>
                <td class="mono" :title="rx ? titles.get(rx.id) : ''">{{ rx?.id ?? "" }}</td>
                <td class="num" data-extent>
                  {{ rx ? extentText(rx.extent_kmol_h) : "" }}
                  <div v-if="rx && rx.rate !== null" class="muted small" data-rate>rate {{ rx.rate.toPrecision(4) }} {{ rx.rate_unit ?? "" }}</div>
                </td>
                <td class="num" data-approach>
                  <template v-if="rx && rx.ln_q_over_k !== null">
                    {{ lnText(rx.ln_q_over_k) }}
                    <span class="badge" :class="approachOf(rx.ln_q_over_k).tone">{{ approachOf(rx.ln_q_over_k).text }}</span>
                  </template>
                </td>
                <template v-if="i === 0">
                  <td class="num" :rowspan="Math.max(row.reactions.length, 1)" data-duty>{{ dutyText(row) }}</td>
                  <td :rowspan="Math.max(row.reactions.length, 1)" class="missing" data-missing>
                    <div v-for="m in row.missing" :key="m" class="warn small">{{ m }}</div>
                  </td>
                </template>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

      <template v-if="beds.length">
        <h2>Fixed beds <span class="muted count">{{ beds.length }}</span> <span class="muted small">(<code>reactor: pfr</code>, temperature and pressure along the catalyst mass, case {{ data.case }})</span></h2>
        <p v-if="simulation.error.value" class="notice warning" data-bed-run-error>The recorded simulation run could not be read: {{ simulation.error.value }}</p>
        <div class="cards">
          <BedProfile
            v-for="b in beds"
            :key="b.node"
            :entry="b"
            :declared="declaredBed(b.node, data.kinetics)"
            :run="bedRunRecord(simulation.data.value, b.node)"
            :case-id="data.case"
            :source="bedSource"
            :snapshot-tool="store.snapshot?.tool ?? null"
            :pid="pidLink(b.node)"
            :csv-name="bedCsvName(b.node)"
          />
        </div>
      </template>

      <h2>Balances <span class="muted small">(reactive blocks and steps, with their extents)</span></h2>
      <div class="table-wrap">
        <table class="data balance-table" aria-label="Reactive balances">
          <thead>
            <tr>
              <th>Block / step</th>
              <th>Status</th>
              <th>Extents</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="b in balances" :key="b.node" :data-balance="b.node" :class="{ error: b.status === 'imbalance' }">
              <td><strong>{{ b.node }}</strong> <span class="faint">{{ b.kind }}</span></td>
              <td><span class="badge" :class="BALANCE_BADGE[b.status]">{{ b.status }}</span></td>
              <td class="mono small">{{ Object.entries(b.extents_kmol_h ?? {}).map(([k, v]) => `${k} ${formatNumber(v)} kmol/h`).join(", ") }}</td>
              <td class="detail">{{ balanceDetail(b) }}</td>
            </tr>
            <tr v-if="!balances.length">
              <td colspan="4" class="muted">No reactive balance.</td>
            </tr>
          </tbody>
        </table>
      </div>
      <FindingsList :findings="findings" label="Reaction findings" />
      <p v-if="!findings.length" class="muted small" data-no-findings>No findings on the reactions, reactors or their balances.</p>

      <section v-if="dataFiles.length" aria-label="Kinetic data" data-kinetic-data>
        <h2>Kinetic data <span class="muted count">{{ dataFiles.length }}</span> <span class="muted small">(<code>{{ kineticData.data.value?.directory }}</code>, fitted as <code>cheme experiments fit-rate</code>)</span></h2>
        <div class="cards">
          <article v-for="f in dataFiles" :key="f.file" class="card data-card" :data-kinetic-file="f.file" :aria-label="`Kinetic data ${f.file}`">
            <header>
              <RouterLink :to="fileLink(f.file)"><strong>{{ f.file.split("/").pop() }}</strong></RouterLink>
              <template v-if="f.data">
                {{ " " }}<span class="muted">{{ f.data.reaction }}<template v-if="f.data.catalyst"> on {{ f.data.catalyst }}</template>, {{ f.data.points.length }} points</span>
                <span class="prov" :class="f.data.provenance" :title="provTitle({ provenance: f.data.provenance, source: f.data.source })">{{ PROVENANCE_SHORT[f.data.provenance] }}</span>
              </template>
            </header>
            <p v-if="f.problem" class="warn small" data-kinetic-problem>{{ f.problem }}</p>
            <template v-if="f.fit">
              <p class="mono expression small" data-fit-law>{{ ordersText(f.fit.rate.orders) ? `r = k · ${Object.entries(f.fit.rate.orders).map(([n, a]) => `p${n}^${sig(a, 3)}`).join(" · ")}` : "r = k" }}{{ f.fit.reverse ? " · (1 − Q/K)" : "" }}</p>
              <dl class="params">
                <dt>R² of ln r</dt>
                <dd data-r2>{{ sig(f.fit.r_squared, 5) }}<template v-if="worstDeviation(fitRows(f)) !== null">, worst point {{ sig(worstDeviation(fitRows(f))! * 100, 3) }} %</template></dd>
                <template v-for="(p, name) in f.fit.parameters" :key="name">
                  <dt>{{ parameterName(String(name)) }}</dt>
                  <dd class="mono small" :data-parameter="name">{{ parameterText(String(name), p) }}</dd>
                </template>
                <dt>Valid</dt>
                <dd>{{ rangeText(f.fit.rate.temperature_range, "K") }}</dd>
              </dl>
              <ul v-if="f.fit.notes.length" class="notes small">
                <li v-for="n in f.fit.notes" :key="n" class="muted">{{ n }}</li>
              </ul>
            </template>
            <details v-if="f.data?.points.length" class="sources">
              <summary>The points{{ f.fit ? " and the fit" : "" }}</summary>
              <div class="table-wrap">
                <table class="data small" :aria-label="`Points of ${f.file}`">
                  <thead>
                    <tr>
                      <th>T (K)</th>
                      <th>p (bar)</th>
                      <th>r ({{ rateUnit(f.data.basis) }})</th>
                      <th v-if="f.fit">fit</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, i) in fitRows(f)" :key="i" data-point>
                      <td class="num">{{ sig(row.temperature, 5) }}</td>
                      <td class="mono">{{ Object.entries(row.pressures).map(([n, v]) => `${n} ${sig(v, 3)}`).join(", ") }}</td>
                      <td class="num">{{ sig(row.measured) }}</td>
                      <td v-if="f.fit" class="num">{{ sig(row.fitted) }}<span v-if="row.deviation !== null" class="muted"> ({{ row.deviation >= 0 ? "+" : "" }}{{ sig(row.deviation * 100, 2) }} %)</span></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </details>
          </article>
        </div>
      </section>

      <section class="kinetics" aria-label="Catalysts" data-kinetics>
        <h2>
          Catalysts <span class="muted count">{{ catalysts.length }}</span>
          <RouterLink v-if="kinetics.file" class="small source-link" :to="fileLink(kinetics.file)">{{ kinetics.file }}</RouterLink>
        </h2>
        <p v-if="!kinetics.file" class="muted" data-no-catalysts>No <code>process/catalysts.yaml</code> (schema <code>cheme schema catalysts</code>).</p>
        <p v-else-if="!catalysts.length" class="muted" data-no-catalysts>No catalysts declared.</p>
        <div v-else class="cards">
          <article v-for="c in catalysts" :id="catalystAnchor(c.id)" :key="c.id" class="card catalyst-card" :class="{ focused: focused === catalystAnchor(c.id) }" :data-catalyst-card="c.id" :aria-label="`Catalyst ${c.id}`">
            <header>
              <strong>{{ c.id }}</strong> <span class="muted">{{ c.name }}</span>
            </header>
            <dl class="params">
              <dt>Active phase</dt>
              <dd data-active-phase>{{ c.active_phase }}</dd>
              <template v-if="c.promoters.length">
                <dt>Promoters</dt>
                <dd>{{ c.promoters.join(", ") }}</dd>
              </template>
              <template v-if="c.support">
                <dt>Support</dt>
                <dd>{{ c.support }}</dd>
              </template>
              <dt>Catalyses</dt>
              <dd data-catalyses>
                <template v-for="(id, i) in c.reactions" :key="id"><template v-if="i">, </template><a href="#" data-link="reaction" @click.prevent="focus(reactionAnchor(id))">{{ id }}</a></template>
                <span v-if="!c.reactions.length" class="muted">no reaction names it</span>
              </dd>
              <dt>Held by</dt>
              <dd data-held-by>
                <div v-for="u in c.units" :key="u.unit">
                  <RouterLink v-if="pidLink(u.unit)" :to="pidLink(u.unit)!" data-link="pid"><strong>{{ u.unit }}</strong></RouterLink>
                  <strong v-else>{{ u.unit }}</strong>
                  {{ " " }}<span class="muted">{{ [u.reactor, bedText(u.bed)].filter(Boolean).join(", ") }}</span>
                  <span v-if="u.bed?.provenance" class="prov" :class="u.bed.provenance" :title="provTitle(u.bed)">{{ PROVENANCE_SHORT[u.bed.provenance] }}</span>
                </div>
                <span v-if="!c.units.length" class="muted">no block or step</span>
              </dd>
            </dl>
            <table class="data small props" :aria-label="`Properties of ${c.id}`">
              <tbody>
                <tr v-if="c.physical" data-physical>
                  <th>Particle and bed</th>
                  <td>
                    {{
                      [
                        c.physical.form,
                        c.physical.particle_diameter ? `d ${formatNumber(c.physical.particle_diameter * 1000)} mm` : "",
                        c.physical.sphericity ? `sphericity ${formatNumber(c.physical.sphericity)}` : "",
                        c.physical.particle_density ? `particle ${formatNumber(c.physical.particle_density)} kg/m³` : "",
                        c.physical.bulk_density ? `bulk ${formatNumber(c.physical.bulk_density)} kg/m³` : "",
                        c.physical.bed_voidage ? `voidage ${formatNumber(c.physical.bed_voidage)}` : "",
                        c.physical.surface_area ? `BET ${formatNumber(c.physical.surface_area)} m²/g` : "",
                      ]
                        .filter(Boolean)
                        .join(", ")
                    }}
                  </td>
                  <td><span class="prov" :class="c.physical.provenance" :title="provTitle(c.physical)">{{ PROVENANCE_SHORT[c.physical.provenance] }}</span></td>
                </tr>
                <tr v-if="c.window" data-window>
                  <th>Window</th>
                  <td>{{ [rangeText(c.window.temperature, "K"), rangeText(c.window.pressure, "kPa(a)")].filter(Boolean).join(", ") }}</td>
                  <td><span class="prov" :class="c.window.provenance" :title="provTitle(c.window)">{{ PROVENANCE_SHORT[c.window.provenance] }}</span></td>
                </tr>
                <tr v-if="c.space_velocity">
                  <th>Space velocity</th>
                  <td>{{ c.space_velocity.basis }} {{ rangeText(c.space_velocity.range, "1/h") }}</td>
                  <td><span class="prov" :class="c.space_velocity.provenance" :title="provTitle(c.space_velocity)">{{ PROVENANCE_SHORT[c.space_velocity.provenance] }}</span></td>
                </tr>
                <tr v-if="c.poisons.length" data-poisons>
                  <th>Poisons</th>
                  <td colspan="2">{{ c.poisons.join(", ") }}</td>
                </tr>
                <tr v-if="c.deactivation" data-deactivation>
                  <th>Deactivation</th>
                  <td>{{ [c.deactivation.lifetime ? `${formatNumber(c.deactivation.lifetime)} years` : "", c.deactivation.mechanisms.join(", "), c.deactivation.regeneration].filter(Boolean).join("; ") }}</td>
                  <td><span class="prov" :class="c.deactivation.provenance" :title="provTitle(c.deactivation)">{{ PROVENANCE_SHORT[c.deactivation.provenance] }}</span></td>
                </tr>
                <tr v-if="c.price" data-price>
                  <th>Price</th>
                  <td>{{ formatNumber(c.price.value) }} {{ c.price.unit }} ({{ c.price.year }})</td>
                  <td><span class="prov" :class="c.price.provenance" :title="provTitle(c.price)">{{ PROVENANCE_SHORT[c.price.provenance] }}</span></td>
                </tr>
              </tbody>
            </table>
            <details v-if="c.sources.length" class="sources">
              <summary>{{ c.sources.length }} source{{ c.sources.length === 1 ? "" : "s" }}</summary>
              <ul>
                <li v-for="(src, i) in c.sources" :key="i">{{ src }}</li>
              </ul>
            </details>
          </article>
        </div>
        <FindingsList :findings="catalystFindings" label="Catalyst findings" />
      </section>
    </template>
  </div>
</template>

<style scoped>
h2 {
  font-size: var(--text-md, 15px);
  margin: var(--space-4) 0 var(--space-2);
}
.count {
  font-weight: 400;
}
.field {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-sm);
}
.small {
  font-size: var(--text-sm);
}
.mono {
  font-family: var(--mono);
  font-size: 12px;
}
td.num {
  text-align: right;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.id-cell .kind {
  margin-left: 4px;
}
.id-cell .title {
  display: block;
}
.equation {
  white-space: nowrap;
}
.source {
  display: block;
  font-size: 11px;
  min-width: 160px;
}
.heat {
  white-space: nowrap;
}
.heat .source {
  white-space: normal;
}
.catalyst {
  min-width: 120px;
}
.places {
  white-space: nowrap;
}
.sources summary {
  font-weight: 400;
  font-size: 11.5px;
  padding: 2px 0;
}
.sources ul {
  margin: 0;
  padding-left: var(--space-4);
  font-size: 11.5px;
  min-width: 220px;
}
.reactor-table tr:not(.first) td {
  border-top: 0;
}
.missing {
  min-width: 160px;
}
.detail {
  min-width: 200px;
}
tr.error td {
  background: var(--bad-soft);
}
.warn {
  color: var(--warn);
}
.err {
  color: var(--bad);
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 380px), 1fr));
  gap: var(--space-3, 12px);
}
.card {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  padding: var(--space-3, 12px);
  min-width: 0;
  overflow-wrap: anywhere;
}
.card header {
  margin-bottom: var(--space-2, 8px);
}
.card.focused,
tr.focused td {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
.expression {
  margin: 0 0 2px;
  white-space: normal;
}
.params {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 2px var(--space-3, 12px);
  margin: var(--space-2, 8px) 0;
  font-size: var(--text-sm);
}
.params dt {
  color: var(--fg-muted);
}
.params dd {
  margin: 0;
  min-width: 0;
}
.source-text {
  font-size: 11.5px;
}
.props th {
  text-align: left;
  font-weight: 500;
  white-space: nowrap;
}
.notes {
  margin: 0 0 var(--space-2, 8px);
  padding-left: var(--space-4);
}
.steps {
  margin: 0;
  padding-left: var(--space-4);
}
.source-link {
  font-weight: 400;
  margin-left: 6px;
}
.bar-groups {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3, 12px);
  margin: var(--space-2, 8px) 0;
}
.bars {
  flex: 1 1 160px;
  min-width: 0;
}
.bar-row {
  display: grid;
  grid-template-columns: minmax(36px, max-content) 1fr max-content;
  align-items: center;
  gap: 6px;
}
.track {
  height: 8px;
  background: var(--border);
  border-radius: 4px;
  overflow: hidden;
}
.fill {
  display: block;
  height: 100%;
  background: var(--accent);
}
.fill.negative {
  background: var(--warn);
}
.bar-value {
  font-variant-numeric: tabular-nums;
  text-align: right;
}
</style>
