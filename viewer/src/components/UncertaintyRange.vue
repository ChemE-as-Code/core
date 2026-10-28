<script setup lang="ts">
/**
 * The 95 % interval of a Monte Carlo total as a bar on an axis from 0, with the median (dot) and
 * the deterministic value (tick). Plain HTML: it reflows with the page.
 */
import { computed } from "vue";
import type { LcaStatistics } from "@/api";
import { impactText, intervalGeometry } from "@/lib/lca";

const props = defineProps<{ stats: LcaStatistics; unit: string }>();
const g = computed(() => intervalGeometry(props.stats));
const pct = (v: number) => `${(v * 100).toFixed(2)}%`;
</script>

<template>
  <div class="range" role="img" :aria-label="`95 % interval ${impactText(stats.low)} to ${impactText(stats.high)} ${unit}, median ${impactText(stats.median)}, deterministic ${impactText(stats.deterministic)}`">
    <div class="track">
      <span class="interval" :style="{ left: pct(g.low), width: pct(g.high - g.low) }" />
      <span class="median" :style="{ left: pct(g.median) }" :title="`median ${impactText(stats.median)} ${unit}`" />
      <span class="deterministic" :style="{ left: pct(g.deterministic) }" :title="`deterministic ${impactText(stats.deterministic)} ${unit}`" />
    </div>
    <div class="axis">
      <span>{{ impactText(g.min) }}</span>
      <span>{{ impactText(g.max) }} {{ unit }}</span>
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
