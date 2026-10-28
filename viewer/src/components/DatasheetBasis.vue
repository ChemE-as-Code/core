<script setup lang="ts">
import { inputsText, inputText, type DatasheetValue } from "@/lib/datasheets";

/**
 * What a datasheet value rests on besides its source: its origin, and the inputs and fingerprint
 * `cheme datasheets fill` calculated it from, as a disclosure (keyboard, touch and screen readers
 * reach the full list as well as the mouse).
 */
defineProps<{ value: Pick<DatasheetValue, "origin" | "inputs" | "fingerprint"> }>();
</script>

<template>
  <div v-if="value.origin || value.inputs.length || value.fingerprint" class="basis" data-basis>
    <span v-if="value.origin" class="badge origin" :data-origin="value.origin" title="What kind of figure it is">{{ value.origin }}</span>
    <details v-if="value.inputs.length || value.fingerprint" class="calc" data-calc>
      <summary data-inputs>
        <template v-if="value.inputs.length"><span class="faint">depends on:</span> {{ inputsText(value) }}</template>
        <template v-else>fingerprint</template>
      </summary>
      <div v-if="value.inputs.length" class="full">
        <span class="faint">Inputs besides the streams:</span>
        <ul data-inputs-full>
          <li v-for="i in value.inputs" :key="i">{{ inputText(i) }}</li>
        </ul>
      </div>
      <p v-if="value.fingerprint" class="full" data-fingerprint>
        <span class="faint">fingerprint:</span> <code>{{ value.fingerprint }}</code>
        <span class="faint">(of the streams and inputs it was filled from; <code>cheme validate</code> reports a mismatch as <code>cheme.datasheet-stale</code>)</span>
      </p>
    </details>
  </div>
</template>

<style scoped>
.basis {
  margin-top: 2px;
}
.origin {
  font-weight: 500;
}
.calc {
  color: var(--fg-muted);
}
.calc summary {
  cursor: pointer;
}
.full {
  margin: 2px 0 0;
}
.full ul {
  margin: 0;
  padding-left: 1.2em;
}
</style>
