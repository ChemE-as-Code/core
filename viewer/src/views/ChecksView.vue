<script setup lang="ts">
import { computed, ref } from "vue";
import { api, type ChecksReport } from "@/api";
import LoadState from "@/components/LoadState.vue";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { shortRev } from "@/lib/format";
import { store } from "@/store";

const { rev } = useRev();
const stored = useAsync((signal) => api.checks({ rev: rev.value }, signal), rev);

const live = ref<ChecksReport | null>(null);
const running = ref(false);
const runError = ref<string | null>(null);
const ranAt = ref<Date | null>(null);

async function runNow(): Promise<void> {
  running.value = true;
  runError.value = null;
  try {
    live.value = await api.runChecks();
    ranAt.value = new Date();
  } catch (e) {
    runError.value = e instanceof Error ? e.message : String(e);
  } finally {
    running.value = false;
  }
}

const report = computed(() => live.value ?? stored.data.value);
const stageTitle = (id: string) => store.repo?.stages.find((s) => s.id === id)?.title ?? id;
const stageOrder = computed(() => new Map((store.repo?.stages ?? []).map((s, i) => [s.id, i] as const)));

const groups = computed(() => {
  const map = new Map<string, NonNullable<typeof report.value>["checks"]>();
  for (const check of report.value?.checks ?? []) {
    const list = map.get(check.stage) ?? [];
    list.push(check);
    map.set(check.stage, list);
  }
  return [...map.entries()].sort(
    ([a], [b]) => (stageOrder.value.get(a) ?? 999) - (stageOrder.value.get(b) ?? 999) || a.localeCompare(b),
  );
});

const totals = computed(() => {
  const out = { pass: 0, fail: 0, na: 0 };
  for (const c of report.value?.checks ?? []) {
    if (c.status === "pass") out.pass++;
    else if (c.status === "fail") out.fail++;
    else out.na++;
  }
  return out;
});

const badgeClass = (status: string) => (status === "pass" ? "pass" : status === "fail" ? "fail" : "na");
</script>

<template>
  <div class="page">
    <h1>
      Engineering-step checks
      <small v-if="live">live run on the working tree{{ ranAt ? `, ${ranAt.toLocaleTimeString()}` : "" }}</small>
      <small v-else>checks/status.json{{ rev ? ` at ${shortRev(rev)}` : " in the working tree" }}</small>
    </h1>
    <div class="toolbar">
      <span class="badge pass">{{ totals.pass }} pass</span>
      <span class="badge fail">{{ totals.fail }} fail</span>
      <span class="badge">{{ totals.na }} n/a</span>
      <span class="spacer" />
      <button v-if="live" class="btn" type="button" @click="live = null">Show stored status</button>
      <button v-if="!store.snapshot" class="btn primary" type="button" :disabled="running" @click="runNow">
        {{ running ? "Running…" : "Run now" }}
      </button>
    </div>
    <p v-if="store.snapshot" class="muted hint">Stored status of the snapshot's revision (checks/status.json); running the checks needs <code>cheme serve</code>.</p>
    <p v-else class="muted hint">"Run now" evaluates checks/checks.yaml on the working tree without writing status.json.</p>

    <div v-if="runError" class="notice error" role="alert">{{ runError }}</div>
    <LoadState :loading="stored.loading.value && !report" :error="live ? null : stored.error.value" @retry="stored.reload" />

    <template v-if="report">
      <p v-if="!report.checks.length" class="notice">
        No check results. Run <code>cheme check</code> to write checks/status.json, or press "Run now".
      </p>
      <section v-for="[stage, checks] in groups" :key="stage" class="stage">
        <h2>
          {{ stageTitle(stage) }}
          <span v-if="store.repo?.stage === stage" class="badge stage">current stage</span>
        </h2>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr><th>status</th><th>check</th><th>title</th><th>detail</th></tr>
            </thead>
            <tbody>
              <tr v-for="c in checks" :key="c.id">
                <td><span class="badge" :class="badgeClass(c.status)">{{ c.status }}</span></td>
                <td><code>{{ c.id }}</code></td>
                <td>{{ c.title }}</td>
                <td class="detail"><pre>{{ c.detail }}</pre></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.hint {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
}
.stage {
  margin-bottom: var(--space-4);
}
h2 {
  font-size: var(--text);
  margin: var(--space-3) 0 var(--space-2);
  display: flex;
  gap: var(--space-2);
  align-items: center;
}
.detail {
  min-width: 200px;
}
.detail pre {
  font-size: var(--text-sm);
}
</style>
