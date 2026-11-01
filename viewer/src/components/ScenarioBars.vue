<script setup lang="ts">
/**
 * One stacked bar per scenario (`scenarioBars` in `src/lib/lca.ts`): each contributor a segment in
 * its colour, credits left of the zero line, the total at the end, a legend below. Plain HTML, so
 * it reflows with the page. A scenario lacking data the baseline has gets no bar and no total:
 * a shorter bar would read as a lower footprint.
 */
import { colourOf, impactText, labelOf, type Bars } from "@/lib/lca";
import type { LcaReport } from "@/api";

const props = defineProps<{ bars: Bars; unit: string; report: Pick<LcaReport, "inventory"> }>();

const pct = (v: number) => `${(v * 100).toFixed(3)}%`;
const colour = (key: string) => `var(--chart-${colourOf(key, props.bars.keys)})`;
</script>

<template>
  <div class="scenario-bars">
    <div v-for="bar in bars.bars" :key="bar.scenario" class="row" :data-scenario="bar.scenario">
      <span class="name">{{ bar.scenario }}</span>
      <p v-if="bar.none" class="dropped" data-not-comparable>
        <template v-if="bar.dropped.length">not comparable: no background here for {{ bar.dropped.map((k) => labelOf(report, k)).join(", ") }}; no total</template>
        <template v-else>no total: every contribution is a data gap</template>
      </p>
      <div v-else class="track" role="img" :aria-label="`${bar.scenario}: ${impactText(bar.total)} ${unit}`">
        <span v-if="bars.zero > 0" class="zero" :style="{ left: pct(bars.zero) }" />
        <span
          v-for="segment in bar.segments"
          :key="segment.key"
          class="segment"
          :class="{ credit: segment.value < 0 }"
          :data-key="segment.key"
          :style="{ left: pct(segment.from), width: pct(segment.to - segment.from), background: segment.value < 0 ? undefined : colour(segment.key) }"
          :title="`${segment.label}: ${impactText(segment.value)} ${unit}`"
        />
      </div>
      <span class="total" data-total>{{ bar.none ? "–" : `${impactText(bar.total)} ${unit}` }}</span>
    </div>
    <ul class="legend" aria-label="Contributors">
      <li v-for="key in bars.keys" :key="key">
        <span class="swatch" :style="{ background: colour(key) }" />
        {{ labelOf(report, key) }}
      </li>
    </ul>
  </div>
</template>

<style scoped>
.scenario-bars {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  font-size: var(--text-sm);
}
.row {
  display: grid;
  grid-template-columns: minmax(80px, max-content) 1fr minmax(110px, max-content);
  gap: var(--space-2);
  align-items: center;
}
.name {
  font-family: var(--mono);
}
.track {
  position: relative;
  height: 22px;
  background: var(--bg-soft);
  border-radius: var(--radius);
  overflow: hidden;
}
.segment {
  position: absolute;
  top: 0;
  bottom: 0;
  border-right: 1px solid var(--surface);
}
.segment.credit {
  background: repeating-linear-gradient(45deg, var(--ok) 0 3px, var(--surface) 3px 6px);
}
.zero {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--fg);
  z-index: 1;
}
.dropped {
  margin: 0;
  color: var(--warn, var(--fg-muted));
  font-size: var(--text-sm);
}
.total {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.legend {
  list-style: none;
  margin: var(--space-1) 0 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-3);
  color: var(--fg-muted);
}
.swatch {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  margin-right: 4px;
  vertical-align: -1px;
}
</style>
