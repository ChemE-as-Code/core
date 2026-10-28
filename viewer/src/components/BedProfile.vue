<script setup lang="ts">
/**
 * One fixed bed of `/api/reactions` (pre-release viewer issue 32): core's solved bed (inlet, outlet, peak, pressure
 * drop, catalyst mass, calculation mode), its temperature and pressure along the catalyst mass
 * with the peak and the reference temperatures, the profile as a table and CSV, core's notes, the
 * bed's row of a recorded simulation run (current, stale or not converged), what the result is
 * from, and the scope of core's model. A bed core could not solve shows why instead.
 */
import { computed } from "vue";
import type { RouteLocationRaw } from "vue-router";
import BedChart from "@/components/BedChart.vue";
import { bedMode, isConstant, peakPlace, profileCsv, temperatureReferences, type BedEntry, type BedRunRecord, type DeclaredBed } from "@/lib/fixedBed";
import { formatNumber } from "@/lib/process";
import { runTime } from "@/lib/simulation";

const props = defineProps<{
  entry: BedEntry;
  declared: DeclaredBed | null;
  run: BedRunRecord | null;
  caseId: string;
  /** What the result is from: `commit 1a2b3c4`, `the working tree`. */
  source: string;
  /** The cheme-as-code version that wrote the static snapshot shown (null on a server, which does not say). */
  snapshotTool: string | null;
  pid: RouteLocationRaw | null;
  /** The file name of the CSV download. */
  csvName: string;
}>();

const bed = computed(() => props.entry.bed);
const mode = computed(() => bedMode(props.declared));
const references = computed(() => temperatureReferences(props.declared));
const place = computed(() => (bed.value ? peakPlace(bed.value) : null));
const inlet = computed(() => bed.value?.profile[0] ?? null);
const tPoints = computed(() => (bed.value?.profile ?? []).map((p) => [p.catalyst_mass_kg, p.temperature_K] as [number, number]));
const pPoints = computed(() => (bed.value?.profile ?? []).map((p) => [p.catalyst_mass_kg, p.pressure_kPa] as [number, number]));
const flatT = computed(() => (bed.value ? isConstant(bed.value, "temperature_K") : false));
const flatP = computed(() => (bed.value ? isConstant(bed.value, "pressure_kPa") : false));
const peak = computed(() => (bed.value && place.value && !place.value.uniform ? { value: bed.value.hot_spot_K, at: [...(place.value.inlet ? [0] : []), ...place.value.interior, ...(place.value.outlet ? [bed.value.catalyst_mass_kg] : [])] } : null));

const num = (v: number | null | undefined, unit = "", digits = 6) => (v === null || v === undefined ? "" : `${formatNumber(Number(v.toPrecision(digits)))}${unit ? ` ${unit}` : ""}`);
const signed = (v: number, unit: string) => `${v > 0 ? "+" : v < 0 ? "−" : "±"}${num(Math.abs(v), unit)}`;

/** `cooled: coolant 620 K, U 30 W/(m² K), 800 tubes of 0.1 m`. */
const modeText = computed(() => {
  const b = props.declared?.bed;
  if (!b || !mode.value) return "";
  const parts: string[] = [];
  if (typeof b.coolant_temperature === "number") parts.push(`coolant ${num(b.coolant_temperature, "K")}`);
  if (typeof b.heat_transfer_coefficient === "number") parts.push(`U ${num(b.heat_transfer_coefficient, "W/(m² K)")}`);
  if (typeof b.tubes === "number" && b.tubes > 1) parts.push(`${b.tubes} tubes${typeof b.diameter === "number" ? ` of ${num(b.diameter, "m")}` : ""}`);
  else if (typeof b.diameter === "number") parts.push(`diameter ${num(b.diameter, "m")}`);
  return parts.length ? `${mode.value}: ${parts.join(", ")}` : mode.value;
});

/** Where core's peak is, in words; never a position core does not give. */
const placeText = computed(() => {
  const p = place.value;
  const b = bed.value;
  if (!p || !b) return "";
  if (p.uniform) return "every sampled point has this temperature";
  if (p.between) return "no sampled point has this value: an interior hot spot between two of them; core reports its value, not its catalyst mass";
  const where = [p.inlet ? `the inlet (0 kg)` : "", ...p.interior.map((w) => `${num(w, "kg")} (inside the bed)`), p.outlet ? `the outlet (${num(b.catalyst_mass_kg, "kg")})` : ""].filter(Boolean);
  const kind = p.interior.length ? "an interior hot spot" : "an endpoint maximum, no interior hot spot";
  return `the sampled value at ${where.join(" and ")}: ${kind}`;
});

function downloadCsv(): void {
  if (!bed.value) return;
  const url = URL.createObjectURL(new Blob([profileCsv(bed.value)], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = props.csvName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const RUN_STATE = {
  current: { badge: "pass", label: "current", title: "The inputs have not changed since the run" },
  stale: { badge: "warning", label: "stale", title: "The inputs changed since the run: its values are historical" },
  failed: { badge: "fail", label: "not converged", title: "The run did not converge: no converged bed result" },
  unknown: { badge: "", label: "staleness unknown", title: "Core cannot tell whether the inputs changed since the run" },
} as const;
</script>

<template>
  <article class="card bed-card" :data-bed="entry.node" :data-bed-state="bed ? 'solved' : 'failed'" :aria-label="`Fixed bed ${entry.node}`">
    <header>
      <RouterLink v-if="pid" :to="pid" data-link="pid" :title="`Open ${entry.node} on its P&ID`"><strong>{{ entry.node }}</strong></RouterLink>
      <strong v-else>{{ entry.node }}</strong>
      <span class="muted"> {{ entry.row.streams_in.join(", ") }} → {{ entry.row.streams_out.join(", ") }}, case {{ caseId }}</span>
      <span v-if="mode" class="badge" data-bed-mode>{{ mode }}</span>
    </header>

    <div v-if="!bed" class="notice error failure" data-bed-failure>
      <p><strong>Not solved:</strong> core could not solve this bed{{ entry.failure.length ? ":" : " and gives no reason." }}</p>
      <ul v-if="entry.failure.length">
        <li v-for="f in entry.failure" :key="f">{{ f }}</li>
      </ul>
      <p class="muted small">No profile, peak or outlet of the bed is shown until it can be solved.</p>
    </div>

    <template v-else>
      <dl class="params">
        <dt>Calculation mode</dt>
        <dd data-bed-mode-text>{{ modeText || "not reported by this server" }}</dd>
        <dt>Catalyst</dt>
        <dd data-bed-catalyst>{{ num(bed.catalyst_mass_kg, "kg") }}, {{ num(bed.catalyst_volume_m3, "m³", 4) }} of bed<template v-if="declared"> ({{ declared.catalyst.id }})</template></dd>
        <dt>Inlet</dt>
        <dd data-bed-inlet>{{ num(inlet?.temperature_K, "K") }}, {{ num(inlet?.pressure_kPa, "kPa") }}</dd>
        <dt>Outlet</dt>
        <dd data-bed-outlet>{{ num(bed.outlet_temperature_K, "K") }}, {{ num(bed.outlet_pressure_kPa, "kPa") }}</dd>
        <dt>Temperature change</dt>
        <dd data-bed-rise>{{ inlet ? signed(bed.outlet_temperature_K - inlet.temperature_K, "K") : "" }} <span class="muted">(T out − T in)</span></dd>
        <dt>Pressure drop</dt>
        <dd data-pressure-drop>{{ num(bed.pressure_drop_kPa, "kPa", 4) }}<span v-if="flatP" class="muted"> (none calculated)</span></dd>
        <dt>Peak temperature</dt>
        <dd data-hot-spot>
          <strong>{{ num(bed.hot_spot_K, "K") }}</strong> <span class="muted">core's, tracked over every integration step</span>
          <div class="small" data-peak-place>{{ placeText }}</div>
        </dd>
        <dt>Resolution</dt>
        <dd class="small" data-bed-resolution>
          {{ bed.profile.length }} sampled points over {{ num(bed.catalyst_mass_kg, "kg") }}
          <div v-if="place?.between" class="warn" data-refine>
            The drawn profile does not reach the peak: it is narrower than the sampling. Core reports no finer profile or the peak's position; check it with a finer solution before relying on the curve.
          </div>
        </dd>
        <dt>Limit</dt>
        <dd class="small" data-bed-limit>
          No engineering maximum allowable temperature is served with this bed: the peak is reported without a safe or unsafe judgement.
        </dd>
      </dl>

      <div v-if="bed.notes.length" class="notes small" data-bed-notes>
        <strong>Core's notes</strong>
        <ul>
          <li v-for="n in bed.notes" :key="n">{{ n }}</li>
        </ul>
      </div>

      <div class="charts">
        <BedChart v-if="!flatT" :points="tPoints" quantity="T" unit="K" :label="`Temperature along the catalyst of ${entry.node}`" :peak="peak" :references="references" />
        <p v-else class="muted small flat" data-flat="temperature">Temperature {{ num(inlet?.temperature_K, "K") }} at every sampled point{{ mode === "isothermal" ? " (isothermal bed)" : "" }}: no temperature profile to draw.</p>
        <BedChart v-if="!flatP" :points="pPoints" quantity="P" unit="kPa" :label="`Pressure along the catalyst of ${entry.node}`" />
        <p v-else class="muted small flat" data-flat="pressure">Pressure {{ num(inlet?.pressure_kPa, "kPa") }} at every sampled point: no pressure profile to draw{{ bed.notes.some((n) => n.startsWith("no pressure drop")) ? " (core calculated no pressure drop, see its notes)" : "" }}.</p>
      </div>

      <details class="profile-table">
        <summary>Profile table ({{ bed.profile.length }} points)</summary>
        <button type="button" class="btn" data-action="bed-csv" @click="downloadCsv">Download CSV</button>
        <div class="table-wrap">
          <table class="data" :aria-label="`Profile of ${entry.node}`">
            <thead>
              <tr>
                <th scope="col">Catalyst mass (kg)</th>
                <th scope="col">T (K)</th>
                <th scope="col">P (kPa)</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(p, i) in bed.profile" :key="i" :class="{ peak: p.temperature_K === bed.hot_spot_K && !place?.uniform }">
                <td class="num">{{ p.catalyst_mass_kg }}<span v-if="i === 0" class="muted"> inlet</span><span v-else-if="i === bed.profile.length - 1" class="muted"> outlet</span></td>
                <td class="num">{{ p.temperature_K }}<span v-if="p.temperature_K === bed.hot_spot_K && !place?.uniform" class="muted"> peak</span></td>
                <td class="num">{{ p.pressure_kPa }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>
    </template>

    <section v-if="run" class="run small" :aria-label="`Recorded simulation run of ${entry.node}`" data-bed-run>
      <strong>Recorded simulation run</strong>
      <span class="badge" :class="RUN_STATE[run.state].badge" :title="RUN_STATE[run.state].title" data-run-state>{{ RUN_STATE[run.state].label }}</span>
      <div class="muted">{{ runTime(run.run_at) }}, {{ run.tool }}<template v-if="run.commit">, inputs at {{ run.commit.slice(0, 7) }}</template>, fingerprint <code>{{ run.model_fingerprint }}</code></div>
      <div v-if="run.state !== 'failed'" data-run-values>
        <template v-if="run.state === 'stale'">Historical: </template>peak {{ num(run.hot_spot_K, "K") || "not recorded" }}, pressure drop {{ num(run.pressure_drop_kPa, "kPa", 4) || "not recorded" }}
      </div>
      <div v-if="run.stale" class="warn" data-run-stale>The inputs changed since the run<template v-if="run.changed.length"> ({{ run.changed.join(", ") }})</template>: run <code>cheme process simulate --fill</code> again for current values.</div>
      <div v-if="run.state === 'failed'" class="err" data-run-failed>
        The run did not converge<template v-if="run.loop && run.loop.converged === false && run.loop.iterations !== null">: the outer loop around the bed stopped after {{ run.loop.iterations }}<template v-if="run.loop.max_iterations !== null"> of {{ run.loop.max_iterations }}</template> DWSIM solves</template>; no converged bed result (core keeps only the last, unconverged iterate).
      </div>
      <ul v-if="run.messages.length">
        <li v-for="m in run.messages" :key="m">{{ m }}</li>
      </ul>
    </section>

    <p class="muted small provenance" data-bed-source>
      <template v-if="snapshotTool">From the static snapshot of {{ source }} written by {{ snapshotTool }}</template>
      <template v-else>Solved by core from the inputs of {{ source }} when the server answered</template>
      (<code>cheme process reactors</code>, case {{ caseId }}). Core serves no input fingerprint<template v-if="!snapshotTool"> or model version</template> with the bed.
    </p>
    <p class="muted small scope">
      Core's model: one-dimensional, pseudo-homogeneous plug flow at steady state, ideal gas, rate laws as effective particle rates. The peak is an axial steady-state screening value: it is not a dynamic
      runaway, thermal-stability or particle hot-spot analysis, and no radial or intraparticle temperature is resolved. Core returns no composition or conversion along the bed.
    </p>
  </article>
</template>

<style scoped>
.bed-card {
  grid-column: 1 / -1;
}
.bed-card header {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
  align-items: baseline;
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
.charts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 340px), 1fr));
  gap: var(--space-4, 16px);
  margin: var(--space-2, 8px) 0;
}
.notes ul,
.run ul,
.failure ul {
  margin: 2px 0;
  padding-left: 1.2em;
}
.failure {
  margin: var(--space-2, 8px) 0;
}
.failure p {
  margin: 2px 0;
}
.profile-table {
  margin: var(--space-2, 8px) 0;
}
.profile-table .btn {
  margin: var(--space-2, 8px) 0;
}
.profile-table .table-wrap {
  max-height: 320px;
  overflow: auto;
}
tr.peak td {
  font-weight: 600;
}
.run {
  border-top: 1px solid var(--border);
  padding-top: var(--space-2, 8px);
  margin-top: var(--space-2, 8px);
}
.run > div {
  margin-top: 2px;
}
.provenance,
.scope {
  margin: var(--space-2, 8px) 0 0;
}
.small {
  font-size: var(--text-sm);
}
.warn {
  color: var(--warn);
}
.err {
  color: var(--bad);
}
@media (max-width: 480px) {
  .params {
    grid-template-columns: 1fr;
  }
  .params dt {
    margin-top: 4px;
  }
}
</style>
