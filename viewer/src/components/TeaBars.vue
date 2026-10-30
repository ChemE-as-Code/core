<script setup lang="ts">
/**
 * Horizontal bars on one axis (`BarChart` of `src/lib/tea.ts`): the TEA's scenarios (from 0,
 * toned by the threshold) and its tornado (around the baseline, the input's low and high end).
 * Vertical marks for 0, the threshold, the baseline. Plain HTML: it reflows with the page.
 */
import type { BarChart } from "@/lib/tea";

defineProps<{ chart: BarChart; label: string; format: (value: number) => string; legend?: { tone: string; label: string }[] }>();
const pct = (v: number) => `${(Math.max(0, Math.min(1, v)) * 100).toFixed(3)}%`;
</script>

<template>
  <div class="tea-bars" role="group" :aria-label="label">
    <div v-for="row in chart.rows" :key="row.key" class="row" :class="{ emphasis: row.emphasis }" :data-bar="row.key">
      <span class="name" :title="row.title ?? row.label">{{ row.label }}</span>
      <div class="track" role="img" :aria-label="`${row.label}: ${row.text}`">
        <span v-for="m in chart.marks" :key="m.key" class="mark" :class="m.key" :style="{ left: pct(m.at) }" />
        <span v-for="(s, i) in row.segments" :key="i" class="segment" :class="s.tone" :style="{ left: pct(s.from), width: pct(s.to - s.from) }" :title="s.title" />
      </div>
      <span class="value" data-value>{{ row.text }}</span>
    </div>
    <div class="row axis-row" aria-hidden="true">
      <span />
      <div class="axis">
        <span>{{ format(chart.domain.min) }}</span>
        <span>{{ format(chart.domain.max) }}</span>
      </div>
      <span />
    </div>
    <ul class="legend">
      <li v-for="m in chart.marks" :key="m.key"><span class="swatch-line" :class="m.key" />{{ m.label }}</li>
      <li v-for="l in legend ?? []" :key="l.tone"><span class="swatch" :class="l.tone" />{{ l.label }}</li>
    </ul>
  </div>
</template>

<style scoped>
/* One grid for all rows (rows are display: contents), so every track has the same width and
   the marks line up. */
.tea-bars {
  display: grid;
  grid-template-columns: minmax(90px, max-content) minmax(0, 1fr) max-content;
  gap: 4px var(--space-2);
  align-items: center;
  font-size: var(--text-sm);
}
.row {
  display: contents;
}
.name {
  max-width: 18rem;
}
.name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.emphasis .name,
.emphasis .value {
  font-weight: 600;
}
.track {
  position: relative;
  height: 16px;
  background: var(--bg-soft);
  border-radius: 2px;
}
.segment {
  position: absolute;
  top: 2px;
  bottom: 2px;
  min-width: 1px;
  background: var(--chart-0);
  border-radius: 2px;
}
.segment.good {
  background: var(--ok);
  opacity: 0.75;
}
.segment.bad {
  background: var(--bad);
  opacity: 0.75;
}
.segment.neutral {
  background: var(--chart-1);
  opacity: 0.75;
}
.segment.low {
  background: var(--chart-1);
}
.segment.high {
  background: var(--chart-2);
}
.mark {
  position: absolute;
  top: -2px;
  bottom: -2px;
  width: 0;
  border-left: 1px solid var(--fg-muted);
  z-index: 1;
}
.mark.threshold {
  border-left: 2px dashed var(--warn);
}
.mark.baseline {
  border-left: 2px solid var(--fg);
}
.value {
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.axis {
  display: flex;
  justify-content: space-between;
  color: var(--fg-muted);
  font-variant-numeric: tabular-nums;
}
.legend {
  grid-column: 1 / -1;
  list-style: none;
  margin: var(--space-1) 0 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-3);
  color: var(--fg-muted);
}
.legend li {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}
.swatch {
  display: inline-block;
  width: 12px;
  height: 10px;
  border-radius: 2px;
}
.swatch.low {
  background: var(--chart-1);
}
.swatch.high {
  background: var(--chart-2);
}
.swatch.good {
  background: var(--ok);
}
.swatch.bad {
  background: var(--bad);
}
.swatch-line {
  display: inline-block;
  width: 0;
  height: 12px;
  border-left: 1px solid var(--fg-muted);
}
.swatch-line.threshold {
  border-left: 2px dashed var(--warn);
}
.swatch-line.baseline {
  border-left: 2px solid var(--fg);
}
@media (max-width: 560px) {
  .tea-bars {
    grid-template-columns: minmax(0, 1fr) max-content;
  }
  .row .name {
    grid-column: 1 / -1;
    max-width: none;
    margin-top: 2px;
  }
  .axis-row > span {
    display: none;
  }
}
</style>
