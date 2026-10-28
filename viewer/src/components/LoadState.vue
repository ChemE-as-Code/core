<script setup lang="ts">
defineProps<{ loading?: boolean; error?: string | null }>();
defineEmits<{ retry: [] }>();
</script>

<template>
  <div v-if="error" class="notice error" role="alert">
    {{ error }}
    <button class="btn retry" type="button" @click="$emit('retry')">Retry</button>
  </div>
  <p v-else-if="loading" class="muted loading" aria-live="polite">Loading&hellip;</p>
</template>

<style scoped>
.retry {
  margin-left: var(--space-2);
}
.loading {
  margin: var(--space-3) 0;
}
</style>
