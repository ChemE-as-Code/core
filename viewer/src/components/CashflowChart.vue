<script setup lang="ts">
/**
 * The cash flow per year (`cashflowChart` of `src/lib/tea.ts`): a bar per year, construction and
 * operation toned apart, below or above the zero line, and the cumulative line over it. Bars are
 * plain HTML; the line is an SVG stretched over the same box, so both reflow with the page.
 */
import { computed } from "vue";
import type { CashflowChart } from "@/lib/tea";

const props = defineProps<{ chart: CashflowChart; format: (value: number) => string; label: string }>();
const n = computed(() => props.chart.bars.length);
const line = computed(() =>
  props.chart.bars
    .map((b, i) => (b.point === null ? null : `${i + 0.5},${b.point.toFixed(3)}`))
    .filter(Boolean)
    .join(" "),
);
const phases = computed(() => [...new Set(props.chart.bars.map((b) => b.phase).filter(Boolean))]);
</script>

<template>
  <figure class="cashflow" :aria-label="label">
    <div class="plot" role="img" :aria-label="`${label}: ${chart.bars.length} years, ${format(chart.min)} to ${format(chart.max)}`">
      <span class="axis-label top">{{ format(chart.max) }}</span>
      <span class="axis-label bottom">{{ format(chart.min) }}</span>
      <span class="zero" :style="{ top: `${chart.zero}%` }" />
      <div class="bars">
        <span v-for="b in chart.bars" :key="b.year" class="slot" :data-year="b.year">
          <span class="bar" :class="[b.phase, { negative: b.value < 0 }]" :style="{ top: `${b.top}%`, height: `${Math.max(b.height, 0.3)}%` }" :title="`year ${b.year} (${b.phase}): ${format(b.value)}${b.cumulative !== null ? `, cumulative ${format(b.cumulative)}` : ''}`" />
        </span>
      </div>
      <svg v-if="line" class="line" :viewBox="`0 0 ${n} 100`" preserveAspectRatio="none" aria-hidden="true">
        <polyline :points="line" fill="none" vector-effect="non-scaling-stroke" />
      </svg>
    </div>
    <div class="years" aria-hidden="true">
      <span>{{ chart.bars[0]?.year }}</span>
      <span v-if="chart.breakEvenYear !== null" class="turn">cumulative ≥ 0 in year {{ chart.breakEvenYear }}</span>
      <span>{{ chart.bars[chart.bars.length - 1]?.year }}</span>
    </div>
    <figcaption class="legend">
      <span v-for="p in phases" :key="p"><span class="swatch" :class="p" />{{ p }}</span>
      <span><span class="swatch-line" />{{ chart.line.replace(/_/g, " ") }}</span>
    </figcaption>
  </figure>
</template>

<style scoped>
.cashflow {
  margin: 0;
  font-size: var(--text-sm);
}
.plot {
  position: relative;
  height: 200px;
  margin-left: 64px;
  background: var(--bg-soft);
  border-radius: 2px;
}
.axis-label {
  position: absolute;
  right: calc(100% + 6px);
  color: var(--fg-muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.axis-label.top {
  top: 0;
}
.axis-label.bottom {
  bottom: 0;
}
.zero {
  position: absolute;
  left: 0;
  right: 0;
  height: 0;
  border-top: 1px solid var(--fg-muted);
  z-index: 1;
}
.bars {
  position: absolute;
  inset: 0;
  display: flex;
}
.slot {
  position: relative;
  flex: 1 1 0;
  min-width: 0;
}
.bar {
  position: absolute;
  left: 15%;
  right: 15%;
  background: var(--chart-3);
  opacity: 0.8;
}
.bar.construction {
  background: var(--chart-2);
}
.bar.negative:not(.construction) {
  background: var(--bad);
}
.line {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
  z-index: 2;
}
.line polyline {
  stroke: var(--chart-1);
  stroke-width: 2px;
}
.years {
  display: flex;
  justify-content: space-between;
  margin-left: 64px;
  color: var(--fg-muted);
  font-variant-numeric: tabular-nums;
}
.turn {
  color: var(--fg);
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-3);
  margin-top: var(--space-1);
  color: var(--fg-muted);
}
.legend > span {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}
.swatch {
  display: inline-block;
  width: 12px;
  height: 10px;
  border-radius: 2px;
  background: var(--chart-3);
}
.swatch.construction {
  background: var(--chart-2);
}
.swatch-line {
  display: inline-block;
  width: 14px;
  height: 0;
  border-top: 2px solid var(--chart-1);
}
</style>
