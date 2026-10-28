<script setup lang="ts">
/**
 * A Sankey diagram of a layout from `src/lib/lca.ts` (`layoutSankey`): nodes as bars, links as
 * bands coloured by the contributor they carry; a credit (a negative value) is hatched. Labels sit
 * left of the first column and right of the others. Text only (no v-html).
 */
import { computed } from "vue";
import { colourOf, impactText, type SankeyLayout, type SankeyNode } from "@/lib/lca";

const props = defineProps<{
  layout: SankeyLayout;
  /** The contributors in colour order (see `colourOf`). */
  keys: readonly string[];
  unit: string;
  /** Accessible name of the chart. */
  title: string;
}>();

/** Room for the labels left of the first column and right of the last. */
const LEFT = 220;
const RIGHT = 150;
const PAD = 12;

const firstColumn = computed(() => Math.min(...props.layout.nodes.map((n) => n.x)));
const lastColumn = computed(() => Math.max(...props.layout.nodes.map((n) => n.x)));
const viewBox = computed(() => `${-LEFT} ${-PAD} ${props.layout.width + LEFT + RIGHT} ${props.layout.height + 2 * PAD}`);

function colour(key: string): string {
  if (key.startsWith("phase:")) return "var(--fg-faint)";
  return `var(--chart-${colourOf(key, props.keys)})`;
}
function nodeColour(node: SankeyNode): string {
  if (node.kind === "flow") return colour(node.id.replace(/^flow:/, ""));
  return node.kind === "total" ? "var(--fg)" : "var(--fg-muted)";
}
function labelX(node: SankeyNode): number {
  if (node.x === firstColumn.value) return node.x - 6;
  return node.x + node.width + 6;
}
function anchor(node: SankeyNode): string {
  return node.x === firstColumn.value ? "end" : "start";
}
/** A label too long for its side is cut with an ellipsis (the full text is in the tooltip). */
function short(text: string, side: number): string {
  const max = Math.floor(side / 7);
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
function side(node: SankeyNode): number {
  if (node.x === firstColumn.value) return LEFT - 10;
  if (node.x === lastColumn.value) return RIGHT - 10;
  return 160;
}
</script>

<template>
  <div class="sankey-scroll">
  <svg class="sankey" :viewBox="viewBox" role="img" :aria-label="title" preserveAspectRatio="xMidYMid meet">
    <defs>
      <pattern id="sankey-credit" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
        <rect width="6" height="6" fill="var(--surface)" />
        <line x1="0" y1="0" x2="0" y2="6" stroke="var(--ok)" stroke-width="3" />
      </pattern>
    </defs>
    <g class="links">
      <path
        v-for="(link, i) in layout.links"
        :key="`${link.source}>${link.target}#${i}`"
        :d="link.path"
        :fill="link.credit ? 'url(#sankey-credit)' : colour(link.key)"
        :class="{ credit: link.credit, thin: link.width < 1.5 }"
        :stroke="link.width < 1.5 ? colour(link.key) : undefined"
        :data-link="link.key"
      >
        <title>{{ link.credit ? "credit: " : "" }}{{ impactText(link.value) }} {{ unit }}</title>
      </path>
    </g>
    <g class="nodes">
      <g v-for="node in layout.nodes" :key="node.id" :data-node="node.id" :class="node.kind">
        <rect :x="node.x" :y="node.y" :width="node.width" :height="Math.max(node.height, 1)" :fill="nodeColour(node)" rx="2" />
        <text :x="labelX(node)" :y="node.y + node.height / 2" :text-anchor="anchor(node)" dominant-baseline="middle">
          <tspan class="label">{{ short(node.label, side(node)) }}</tspan>
          <tspan class="value" :x="labelX(node)" dy="1.2em">{{ impactText(node.value) }} {{ unit }}</tspan>
          <title>{{ node.label }}: {{ impactText(node.value) }} {{ unit }}</title>
        </text>
      </g>
    </g>
  </svg>
  </div>
</template>

<style scoped>
/* On a narrow screen the chart keeps a readable size and scrolls sideways on its own. */
.sankey-scroll {
  overflow-x: auto;
}
.sankey {
  min-width: 640px;
  width: 100%;
  height: auto;
  display: block;
  font-family: var(--font);
}
.links path {
  opacity: 0.55;
  transition: opacity 0.15s;
}
.links path:hover {
  opacity: 0.9;
}
.links path.credit {
  opacity: 0.8;
}
/* A band thinner than a pixel stays visible as a line. */
.links path.thin {
  stroke-width: 1.2;
  opacity: 0.8;
}
text {
  fill: var(--fg);
  font-size: 12px;
}
.value {
  fill: var(--fg-muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.total .label {
  font-weight: 600;
}
</style>
