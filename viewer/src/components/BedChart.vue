<script setup lang="ts">
/**
 * One quantity of a fixed bed along its catalyst mass (pre-release viewer issue 32): core's sampled profile, the
 * inlet and outlet marked; for the temperature also core's peak (a marker where it is a sampled
 * point, else a dashed line at its value: core does not report where it is) and reference lines
 * (coolant, catalyst window), each with its own dash pattern and a legend entry. Hovering, or
 * the arrow keys on the focused chart, steps through the sampled points and reads each out below.
 */
import { computed, ref } from "vue";
import { chartScale, nearestIndex, type TemperatureReference } from "@/lib/fixedBed";
import { formatNumber } from "@/lib/process";

const props = defineProps<{
  points: readonly [number, number][];
  /** The quantity and its unit: `T`, `K`. */
  quantity: string;
  unit: string;
  label: string;
  /** Core's peak: at these sampled catalyst masses, or `at` empty for a value core does not place. */
  peak?: { value: number; at: number[] } | null;
  references?: readonly TemperatureReference[];
}>();

const W = 320;
const H = 150;
const PAD = { left: 58, right: 12, top: 10, bottom: 34 };
const refs = computed(() => props.references ?? []);
// y spans the profile, the peak and the coolant; a catalyst window end outside it is listed, not drawn (a wide window would flatten the profile)
const scale = computed(() => chartScale(props.points, [...refs.value.filter((r) => r.kind === "coolant").map((r) => r.value_K), ...(props.peak ? [props.peak.value] : [])], W, H));
const shown = computed(() => refs.value.filter((r) => scale.value && r.value_K >= scale.value.y[0] && r.value_K <= scale.value.y[1]));
/** Whether a legend entry (the window: either end) is not drawn. */
const outside = (r: TemperatureReference) => refs.value.some((m) => (m.kind === r.kind || (r.kind === "catalyst-max" && m.kind === "catalyst-min")) && !shown.value.includes(m));
const fmt = (v: number) => formatNumber(Number(v.toPrecision(6)));
const DASH: Record<TemperatureReference["kind"], string> = { coolant: "8 3 2 3", "catalyst-max": "2 3", "catalyst-min": "2 3" };
const SHORT: Record<TemperatureReference["kind"], string> = { coolant: "coolant", "catalyst-max": "catalyst max", "catalyst-min": "catalyst min" };
/** The legend: one entry for the catalyst window (both its ends). */
const legend = computed(() =>
  refs.value
    .filter((r) => r.kind !== "catalyst-min")
    .map((r) => {
      const lo = r.kind === "catalyst-max" ? refs.value.find((m) => m.kind === "catalyst-min") : undefined;
      return { ...r, text: lo ? `Catalyst window ${fmt(lo.value_K)}–${fmt(r.value_K)} K` : `${r.label} ${fmt(r.value_K)} K` };
    }),
);

const active = ref<number | null>(null);
/** The readout is announced for keyboard steps only, not on every pointer move. */
const fromKeys = ref(false);
const svg = ref<SVGSVGElement | null>(null);
function pointAt(event: PointerEvent): void {
  const s = scale.value;
  if (!s || !svg.value) return;
  const box = svg.value.getBoundingClientRect();
  const x = ((event.clientX - box.left) / box.width) * (W + PAD.left + PAD.right) - PAD.left;
  fromKeys.value = false;
  active.value = nearestIndex(props.points, s.x[0] + (Math.min(Math.max(x, 0), W) / W) * (s.x[1] - s.x[0]));
}
function step(event: KeyboardEvent): void {
  const last = props.points.length - 1;
  const next: Record<string, number> = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 };
  if (event.key in next) active.value = Math.min(Math.max((active.value ?? (next[event.key]! > 0 ? -1 : last + 1)) + next[event.key]!, 0), last);
  else if (event.key === "Home") active.value = 0;
  else if (event.key === "End") active.value = last;
  else if (event.key === "Escape") active.value = null;
  else return;
  fromKeys.value = true;
  event.preventDefault();
}
const readout = computed(() => {
  const i = active.value;
  const p = i === null ? undefined : props.points[i];
  if (!p) return "";
  const where = i === 0 ? " (inlet)" : i === props.points.length - 1 ? " (outlet)" : "";
  return `Catalyst mass ${fmt(p[0])} kg${where}: ${props.quantity} ${fmt(p[1])} ${props.unit}`;
});
</script>

<template>
  <figure class="bed-chart" :aria-label="label" data-bed-chart>
    <svg
      v-if="scale"
      ref="svg"
      :viewBox="`0 0 ${W + PAD.left + PAD.right} ${H + PAD.top + PAD.bottom}`"
      role="img"
      :aria-label="`${label}; the arrow keys read out each sampled point`"
      tabindex="0"
      @pointermove="pointAt"
      @pointerleave="active = null"
      @keydown="step"
      @blur="active = null"
    >
      <g :transform="`translate(${PAD.left},${PAD.top})`">
        <line v-for="t in scale.yTicks" :key="t" class="grid" x1="0" :x2="W" :y1="scale.py(t)" :y2="scale.py(t)" />
        <text v-for="t in scale.yTicks" :key="`t${t}`" class="tick" x="-5" :y="scale.py(t) + 3" text-anchor="end">{{ fmt(t) }}</text>
        <rect class="frame" x="0" y="0" :width="W" :height="H" />
        <line
          v-for="r in shown"
          :key="r.kind"
          class="ref"
          :class="r.kind"
          x1="0"
          :x2="W"
          :y1="scale.py(r.value_K)"
          :y2="scale.py(r.value_K)"
          :stroke-dasharray="DASH[r.kind]"
          :data-reference="r.kind"
        />
        <text v-for="r in shown" :key="`l${r.kind}`" class="ref-label" :x="W - 4" :y="scale.py(r.value_K) - 3" text-anchor="end">{{ SHORT[r.kind] }} {{ fmt(r.value_K) }} K</text>
        <line v-if="peak && !peak.at.length" class="peak-line" x1="0" :x2="W" :y1="scale.py(peak.value)" :y2="scale.py(peak.value)" stroke-dasharray="6 3" data-peak-line />
        <path class="line" :d="scale.d" />
        <circle class="end" :cx="scale.px(points[0]![0])" :cy="scale.py(points[0]![1])" r="3.5" data-inlet />
        <circle class="end outlet" :cx="scale.px(points[points.length - 1]![0])" :cy="scale.py(points[points.length - 1]![1])" r="3.5" data-outlet />
        <circle v-for="x in peak?.at ?? []" :key="`h${x}`" class="peak-halo" :cx="scale.px(x)" :cy="scale.py(peak!.value)" r="5" />
        <circle v-for="x in peak?.at ?? []" :key="x" class="peak" :cx="scale.px(x)" :cy="scale.py(peak!.value)" r="5" data-peak-marker />
        <g v-if="active !== null && points[active]" class="cursor">
          <line :x1="scale.px(points[active]![0])" :x2="scale.px(points[active]![0])" y1="0" :y2="H" />
          <circle :cx="scale.px(points[active]![0])" :cy="scale.py(points[active]![1])" r="4" />
        </g>
        <text class="tick" x="0" :y="H + 13" text-anchor="start" data-x-min>{{ fmt(scale.x[0]) }} (inlet)</text>
        <text class="tick" :x="W" :y="H + 13" text-anchor="end" data-x-max>{{ fmt(scale.x[1]) }} (outlet)</text>
        <text class="axis" :x="W / 2" :y="H + 29" text-anchor="middle">catalyst mass from the inlet (kg)</text>
        <text class="axis" :transform="`translate(-46,${H / 2}) rotate(-90)`" text-anchor="middle">{{ quantity }} ({{ unit }})</text>
      </g>
    </svg>
    <p v-else class="muted small">Too few points to draw.</p>
    <p class="readout small" :aria-live="fromKeys ? 'polite' : 'off'" data-readout>{{ readout || " " }}</p>
    <ul v-if="scale" class="legend small" :aria-label="`Legend of ${label}`">
      <li><span class="swatch line" aria-hidden="true" />core's profile, {{ points.length }} sampled points (inlet ○, outlet ●)</li>
      <li v-if="peak && peak.at.length"><span class="swatch peak-dot" aria-hidden="true" />peak {{ fmt(peak.value) }} {{ unit }} (core's, at a sampled point)</li>
      <li v-if="peak && !peak.at.length"><span class="swatch peak-dash" aria-hidden="true" />peak {{ fmt(peak.value) }} {{ unit }}: core's value, between sampled points, position not reported</li>
      <li v-for="r in legend" :key="r.kind" :data-legend="r.kind">
        <span class="swatch ref" :class="r.kind" aria-hidden="true" />{{ r.text }}<span class="muted">: {{ r.basis }}</span
        ><span v-if="r.provenance" class="muted"> ({{ [r.provenance, r.source].filter(Boolean).join(": ") }})</span
        ><span v-if="outside(r)" class="muted" data-outside> (outside the plotted range: not drawn)</span>
      </li>
    </ul>
  </figure>
</template>

<style scoped>
.bed-chart {
  margin: 0;
  max-width: 560px;
  min-width: 0;
}
svg {
  width: 100%;
  height: auto;
  display: block;
  touch-action: pan-y;
}
svg:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.frame {
  fill: none;
  stroke: var(--border);
}
.grid {
  stroke: var(--border);
  stroke-width: 0.5;
}
.line {
  fill: none;
  stroke: var(--chart-1);
  stroke-width: 2;
}
.end {
  fill: var(--surface);
  stroke: var(--chart-1);
  stroke-width: 2;
}
.end.outlet {
  fill: var(--chart-1);
}
.peak {
  fill: none;
  stroke: var(--chart-2);
  stroke-width: 2.5;
}
.peak-halo {
  fill: none;
  stroke: var(--fg);
  stroke-width: 5;
}
.peak-line {
  stroke: var(--chart-2);
  stroke-width: 1.5;
}
.ref {
  stroke-width: 1.5;
}
.ref {
  stroke: var(--fg-muted);
}
.ref-label {
  font-size: 10px;
  fill: var(--fg-muted);
}
.cursor line {
  stroke: var(--fg-muted);
  stroke-width: 1;
}
.cursor circle {
  fill: var(--fg);
  stroke: var(--surface);
  stroke-width: 2;
}
.tick {
  font-size: 10px;
  fill: var(--fg-muted);
  font-variant-numeric: tabular-nums;
}
.axis {
  font-size: 11px;
  fill: var(--fg);
}
.readout {
  margin: 2px 0 0;
  min-height: 1.4em;
  font-variant-numeric: tabular-nums;
}
.legend {
  list-style: none;
  margin: 4px 0 0;
  padding: 0;
  display: grid;
  gap: 2px;
}
.swatch {
  display: inline-block;
  width: 22px;
  height: 0;
  margin-right: 6px;
  vertical-align: middle;
  border-top: 2px solid var(--chart-1);
}
.swatch.peak-dot {
  width: 10px;
  height: 10px;
  border: 2.5px solid var(--chart-2);
  border-radius: 50%;
  margin: 0 18px 0 6px;
}
.swatch.peak-dash {
  border-top: 2px dashed var(--chart-2);
}
.swatch.ref.coolant {
  border-top: 2px dashed var(--fg-muted);
}
.swatch.ref.catalyst-max,
.swatch.ref.catalyst-min {
  border-top: 2px dotted var(--fg-muted);
}
.small {
  font-size: var(--text-sm);
}
</style>
