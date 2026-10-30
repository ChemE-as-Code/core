<script setup lang="ts">
/**
 * An interval of a Monte Carlo result as a bar on an axis from 0, with the median (dot) and the
 * deterministic value (tick): the LCA's 95 % interval, the TEA's P10..P90 (`label`). `format`
 * writes a number with its unit (money, a percentage); without it, 4 digits and `unit`. Plain
 * HTML: it reflows with the page.
 */
import { computed } from "vue";
import type { LcaStatistics } from "@/api";
import { impactText, intervalGeometry } from "@/lib/lca";

type Interval = Pick<LcaStatistics, "low" | "high" | "median" | "deterministic">;
const props = withDefaults(defineProps<{ stats: Interval; unit: string; label?: string; format?: ((value: number) => string) | undefined }>(), {
  label: "95 % interval",
  format: undefined,
});
const g = computed(() => intervalGeometry(props.stats));
const pct = (v: number) => `${(v * 100).toFixed(2)}%`;
/** A number with its unit. */
const text = (v: number) => (props.format ? props.format(v) : `${impactText(v)} ${props.unit}`.trim());
</script>

<template>
  <div class="range" role="img" :aria-label="`${label} ${text(stats.low)} to ${text(stats.high)}, median ${text(stats.median)}, deterministic ${text(stats.deterministic)}`">
    <div class="track">
      <span class="interval" :style="{ left: pct(g.low), width: pct(g.high - g.low) }" />
      <span class="median" :style="{ left: pct(g.median) }" :title="`median ${text(stats.median)}`" />
      <span class="deterministic" :style="{ left: pct(g.deterministic) }" :title="`deterministic ${text(stats.deterministic)}`" />
    </div>
    <div class="axis">
      <span>{{ format ? format(g.min) : impactText(g.min) }}</span>
      <span>{{ format ? format(g.max) : `${impactText(g.max)} ${unit}` }}</span>
    </div>
  </div>
</template>

<style scoped>
.range {
  font-size: var(--text-sm);
}
.track {
  position: relative;
  height: 18px;
  background: var(--bg-soft);
  border-radius: var(--radius);
}
.interval {
  position: absolute;
  top: 4px;
  bottom: 4px;
  background: var(--chart-1);
  opacity: 0.45;
  border-radius: 3px;
}
.median {
  position: absolute;
  top: 3px;
  width: 12px;
  height: 12px;
  margin-left: -6px;
  border-radius: 50%;
  background: var(--chart-1);
}
.deterministic {
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
</style>
