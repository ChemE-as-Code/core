<script setup lang="ts">
/** A small line chart of one series (k(T) of a rate law, a bed's temperature or pressure along it): the line, the ranges of x and y, their labels. */
import { computed } from "vue";
import { chartGeometry } from "@/lib/reactions";

const props = defineProps<{
  points: readonly [number, number][];
  xLabel: string;
  yLabel: string;
  /** y on a log scale. */
  log?: boolean;
  label: string;
  /** Under the chart (e.g. the unit of y). */
  caption?: string;
  /** Formats the axis values. */
  format?: (v: number) => string;
}>();

const W = 240;
const H = 110;
const PAD = { left: 62, right: 10, top: 10, bottom: 30 };
const geometry = computed(() => chartGeometry(props.points, W, H, props.log ?? false));
/** `573.1`, `7.66e-8`: four digits, small and large values in exponent form. */
const fmt = (v: number) => {
  if (props.format) return props.format(v);
  const a = Math.abs(v);
  return a !== 0 && (a < 1e-3 || a >= 1e6) ? v.toExponential(2) : String(Number(v.toPrecision(4)));
};
</script>

<template>
  <figure class="line-chart" :aria-label="label" data-chart>
    <svg v-if="geometry" :viewBox="`0 0 ${W + PAD.left + PAD.right} ${H + PAD.top + PAD.bottom}`" role="img" :aria-label="label">
      <g :transform="`translate(${PAD.left},${PAD.top})`">
        <rect class="frame" x="0" y="0" :width="W" :height="H" />
        <path class="line" :d="geometry.d" />
        <text class="tick" x="-4" y="8" text-anchor="end" data-y-max>{{ fmt(geometry.y[1]) }}</text>
        <text class="tick" x="-4" :y="H" text-anchor="end" data-y-min>{{ fmt(geometry.y[0]) }}</text>
        <text class="tick" x="0" :y="H + 12" text-anchor="start" data-x-min>{{ fmt(geometry.x[0]) }}</text>
        <text class="tick" :x="W" :y="H + 12" text-anchor="end" data-x-max>{{ fmt(geometry.x[1]) }}</text>
        <text class="axis" :x="W / 2" :y="H + 26" text-anchor="middle">{{ xLabel }}</text>
        <text class="axis" :transform="`translate(-52,${H / 2}) rotate(-90)`" text-anchor="middle">{{ yLabel }}{{ geometry.log ? " (log)" : "" }}</text>
      </g>
    </svg>
    <figcaption v-if="geometry && caption" class="muted small">{{ caption }}</figcaption>
    <p v-else-if="!geometry" class="muted small">Too few points to draw.</p>
  </figure>
</template>

<style scoped>
.line-chart {
  margin: 0;
  max-width: 320px;
}
svg {
  width: 100%;
  height: auto;
  display: block;
}
.frame {
  fill: none;
  stroke: var(--border);
}
.line {
  fill: none;
  stroke: var(--accent);
  stroke-width: 1.6;
}
.tick {
  font-size: 9px;
  fill: var(--fg-muted);
  font-variant-numeric: tabular-nums;
}
.axis {
  font-size: 10px;
  fill: var(--fg);
}
.small {
  font-size: var(--text-sm);
}
</style>
