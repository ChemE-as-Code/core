<script setup lang="ts">
import type { ProcessValue } from "@/api";
import { PROVENANCE_SHORT, formatNumber, formatValue } from "@/lib/process";

withDefaults(defineProps<{ value: ProcessValue | null | undefined; showUnit?: boolean }>(), { showUnit: true });
</script>

<template>
  <span v-if="value" class="pv" :class="{ stale: value.stale }" :title="[value.provenance, value.basis, value.source, value.stale ? 'stale: inputs changed since calculated' : ''].filter(Boolean).join(' · ')">
    {{ showUnit ? formatValue(value) : formatNumber(value.value) }}
    <span class="prov" :class="value.provenance">{{ PROVENANCE_SHORT[value.provenance] }}</span>
    <span v-if="value.stale" class="badge warning">stale</span>
  </span>
</template>
