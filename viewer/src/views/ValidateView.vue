<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { api, ApiError, type Finding, type ImpactReport, type Level } from "@/api";
import LoadState from "@/components/LoadState.vue";
import { useAsync } from "@/lib/useAsync";
import { kindFromPath, pathSegments, viewFor } from "@/lib/format";
import { countLevels, matchesQuery } from "@/lib/findings";
import { store } from "@/store";

const router = useRouter();
const report = useAsync((signal) => api.validate(signal));
/** `cheme impact` of the working tree, or null for a server without `/api/impact` (a 404). */
const impact = useAsync<ImpactReport | null>(async (signal) => {
  try {
    return await api.impact(signal);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
});
const levels: Level[] = ["error", "warning", "info"];
const shown = ref(new Set<Level>(levels));
const query = ref("");

const counts = computed(() => countLevels(report.data.value?.findings ?? []));

const findings = computed(() =>
  (report.data.value?.findings ?? []).filter((f) => shown.value.has(f.level) && matchesQuery(f, query.value)),
);
const reviewNeeded = computed(() => (impact.data.value?.findings ?? []).filter((f) => matchesQuery(f, query.value)));

function reload(): void {
  report.reload();
  impact.reload();
}

function toggle(level: Level): void {
  const next = new Set(shown.value);
  if (next.has(level)) next.delete(level);
  else next.add(level);
  shown.value = next;
}

/** Findings are about the working tree: open the file there, at the line when there is one. */
function open(finding: Finding): void {
  const params = { path: pathSegments(finding.file) };
  // A sheet listed in plant.yaml (e.g. process/BFD.xml) is a drawing wherever it lives.
  const sheet = store.repo?.sheets.some((s) => s.file === finding.file);
  if (finding.line) void router.push({ name: "file", params, query: { line: String(finding.line) } });
  else void router.push({ name: sheet ? "pid" : viewFor(kindFromPath(finding.file)), params });
}
</script>

<template>
  <div class="page">
    <h1>Validation <small>working tree</small></h1>
    <div class="toolbar">
      <div class="levels" role="group" aria-label="Levels">
        <button
          v-for="level in levels"
          :key="level"
          type="button"
          class="btn"
          :class="{ active: shown.has(level) }"
          :aria-pressed="shown.has(level)"
          @click="toggle(level)"
        >
          <span class="badge" :class="level">{{ counts[level] }}</span> {{ level }}
        </button>
      </div>
      <input v-model="query" type="search" placeholder="Filter findings" aria-label="Filter findings" />
      <span class="spacer" />
      <button class="btn" type="button" :disabled="report.loading.value" @click="reload">
        {{ report.loading.value ? "Validating…" : "Validate again" }}
      </button>
    </div>
    <section v-if="impact.data.value?.findings.length" class="review" aria-labelledby="review-title">
      <h2 id="review-title">
        Review needed <span class="badge info">{{ impact.data.value.findings.length }}</span>
      </h2>
      <p class="muted summary">
        These artifacts rest on sources that changed since they were reviewed or generated. Look at them again; cheme-as-code
        does not say they are wrong and regenerates nothing.
      </p>
      <ul class="review-list">
        <li v-for="f in reviewNeeded" :key="f.id ?? `${f.file}:${f.message}`">
          <button type="button" class="finding" :title="`Open ${f.file}`" @click="open(f)">
            <code class="file">{{ f.file }}<template v-if="f.line">:{{ f.line }}</template></code>
            <span>{{ f.message }}</span>
            <span v-if="f.hint" class="muted hint">{{ f.hint }}</span>
          </button>
        </li>
        <li v-if="!reviewNeeded.length" class="muted">No artifacts match the filter.</li>
      </ul>
    </section>
    <p v-else-if="impact.error.value" class="muted summary">Review needed: {{ impact.error.value }}</p>
    <LoadState :loading="report.loading.value && !report.data.value" :error="report.error.value" @retry="report.reload" />
    <template v-if="report.data.value">
      <p class="muted summary">
        {{ report.data.value.files.length }} files checked, {{ report.data.value.findings.length }} findings.
      </p>
      <p v-if="!report.data.value.findings.length" class="notice">Everything validates.</p>
      <div v-else class="table-wrap">
        <table class="data">
          <thead>
            <tr><th>level</th><th>file</th><th>rule</th><th>message</th><th>ids</th></tr>
          </thead>
          <tbody>
            <tr
              v-for="(f, i) in findings"
              :key="i"
              class="clickable"
              tabindex="0"
              :title="`Open ${f.file}`"
              @click="open(f)"
              @keydown.enter="open(f)"
            >
              <td><span class="badge" :class="f.level">{{ f.level }}</span></td>
              <td class="file"><code>{{ f.file }}<template v-if="f.line">:{{ f.line }}</template></code></td>
              <td><code>{{ f.rule }}</code></td>
              <td>
                {{ f.message }}
                <div v-if="f.hint" class="muted hint">{{ f.hint }}</div>
              </td>
              <td><code v-for="id in f.ids" :key="id" class="id">{{ id }}</code></td>
            </tr>
            <tr v-if="!findings.length">
              <td colspan="5" class="muted">No findings match the filter.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<style scoped>
.levels {
  display: flex;
  gap: var(--space-1);
}
.summary {
  margin: 0 0 var(--space-2);
  font-size: var(--text-sm);
}
.file {
  white-space: nowrap;
}
.hint {
  font-size: 12px;
  margin-top: 2px;
}
.id {
  display: inline-block;
  margin: 0 4px 2px 0;
}
.review h2 {
  font-size: var(--text);
  margin: 0 0 var(--space-1);
}
.review-list {
  list-style: none;
  margin: 0 0 var(--space-4);
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.finding {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  width: 100%;
  padding: var(--space-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--fg);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.finding:hover {
  border-color: var(--accent);
}
</style>
