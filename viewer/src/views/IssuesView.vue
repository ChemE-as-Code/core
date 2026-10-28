<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError, type IssuesReport, type IssueStatus, type IssueType } from "@/api";
import LoadState from "@/components/LoadState.vue";
import { loadIssues, store } from "@/store";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { shortRev } from "@/lib/format";
import {
  blockingCurrent,
  disciplinesOf,
  filterIssues,
  groupByGate,
  ISSUE_TYPES,
  newIssueButtons,
  statusLabel,
  TYPE_LABEL,
  typeTone,
  waitingLabel,
  type IssueFilter,
} from "@/lib/issues";

const route = useRoute();
const router = useRouter();
const { rev } = useRev();

/** Why there are no issues to show: the plant tracks none (404) or GitHub cannot be read (503). */
type Missing = { status: 404 | 503; message: string };

let force = false;
async function load(): Promise<IssuesReport | Missing> {
  try {
    return await loadIssues(force);
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 503)) return { status: error.status, message: error.message };
    throw error;
  } finally {
    force = false;
  }
}
const report = useAsync(() => load());
function reload(): void {
  force = true;
  void report.reload();
}
const data = computed(() => (report.data.value && "issues" in report.data.value ? report.data.value : null));
const missing = computed(() => (report.data.value && !("issues" in report.data.value) ? report.data.value : null));

const first = (v: unknown) => (Array.isArray(v) ? v[0] : v);
const param = (key: string) => String(first(route.query[key]) ?? "");
const filter = computed<IssueFilter>(() => ({
  type: param("type") as IssueFilter["type"],
  gate: param("gate"),
  discipline: param("discipline"),
  status: param("status") as IssueStatus | "",
  closed: param("closed") === "1",
}));
function setFilter(key: "type" | "gate" | "discipline" | "status" | "closed", value: string): void {
  const query = { ...route.query };
  if (value) query[key] = value;
  else delete query[key];
  // a closed-only filter means nothing once closed items are hidden again
  if (key === "closed" && !value && query.status === "closed") delete query.status;
  void router.replace({ query });
}

const stageTitle = (id: string | null) => (id === null ? "No gate" : (store.repo?.stages.find((s) => s.id === id)?.title ?? id));
const shown = computed(() => (data.value ? filterIssues(data.value.issues, filter.value) : []));
const groups = computed(() => (data.value ? groupByGate(shown.value, data.value.stages) : []));
const openCount = computed(() => data.value?.issues.filter((i) => i.state === "open").length ?? 0);
const closedCount = computed(() => (data.value?.issues.length ?? 0) - openCount.value);
const blocking = computed(() => (data.value ? blockingCurrent(data.value) : null));
const disciplines = computed(() => (data.value ? disciplinesOf(data.value.issues) : []));
const gates = computed(() => (data.value ? groupByGate(data.value.issues, data.value.stages).map((g) => g.gate) : []));
const buttons = computed(() => (data.value ? newIssueButtons(data.value) : []));
const STATUSES: IssueStatus[] = ["open", "in-progress", "for-verification"];
const typeLabel = (type: IssueType | null) => (type ? TYPE_LABEL[type] : "Untyped");
</script>

<template>
  <div class="page issues">
    <h1>
      Issues
      <small>actions, holds, technical queries and design changes, as GitHub has them now</small>
    </h1>
    <p v-if="rev" class="notice warning" data-issues-rev>
      This page shows the plant's issues as GitHub has them now (they are not part of the repository's history), not at {{ shortRev(rev) }}.
    </p>
    <p v-else-if="store.snapshot && data" class="notice info" data-issues-snapshot>The issues as they were when this snapshot was written.</p>

    <LoadState :loading="report.loading.value && !report.data.value" :error="report.error.value" @retry="reload" />

    <div v-if="missing?.status === 404" class="notice" data-issues-missing>
      <p v-if="store.snapshot && store.repo?.has_issues" data-issues-not-exported>
        <strong>This snapshot does not hold the issues.</strong>
        The plant tracks its issues on GitHub, but <code>cheme export-static</code> records them only for the working tree without
        <code>--exclude</code>.
      </p>
      <p v-else><strong>This plant does not track issues.</strong></p>
      <p class="muted">
        <code>plant.yaml</code> <code>issues: {repository, label}</code> names the GitHub repository and the plant's label; <code>cheme issues</code> lists
        them, and the gates of kind <code>issues</code> fail while an item for the stage is open.
      </p>
    </div>
    <div v-else-if="missing?.status === 503" class="notice error" role="alert" data-issues-unavailable>
      <p><strong>The issues cannot be read now.</strong> {{ missing.message }}</p>
      <p class="muted">
        Start <code>cheme serve</code> with a GitHub token in <code>GITHUB_TOKEN</code> (or <code>GH_TOKEN</code>), or log in with <code>gh auth login</code>,
        and check the network. The <code>issues</code> gates fail as not evaluated meanwhile.
      </p>
      <button class="btn" type="button" @click="reload">Retry</button>
    </div>

    <template v-if="data">
      <p class="summary" data-issues-summary>
        <template v-if="blocking !== null">
          <strong data-issues-blocking>{{ blocking.length }}</strong>
          open {{ blocking.length === 1 ? "item blocks" : "items block" }} the {{ stageTitle(data.stage) }} gate<template v-if="blocking.length">
            ({{ blocking.map((n) => `#${n}`).join(", ") }})</template
          >.
        </template>
        {{ openCount }} open, {{ closedCount }} closed in
        <a :href="data.web" target="_blank" rel="noopener">{{ data.repository }}</a> with the label <code>{{ data.label }}</code>.
      </p>

      <div v-if="buttons.length" class="toolbar new" aria-label="New issue">
        <a v-for="b in buttons" :key="b.key" class="btn" :href="b.url" target="_blank" rel="noopener" :data-new="b.key">{{ b.label }}</a>
      </div>

      <div class="toolbar filters">
        <label>
          Type
          <select data-action="type" :value="filter.type" @change="setFilter('type', ($event.target as HTMLSelectElement).value)">
            <option value="">all</option>
            <option v-for="t in ISSUE_TYPES" :key="t" :value="t">{{ TYPE_LABEL[t] }}</option>
            <option value="untyped">untyped</option>
          </select>
        </label>
        <label>
          Gate
          <select data-action="gate" :value="filter.gate" @change="setFilter('gate', ($event.target as HTMLSelectElement).value)">
            <option value="">all</option>
            <option v-for="g in gates" :key="g ?? 'none'" :value="g ?? 'none'">{{ g === null ? "no gate" : `before ${stageTitle(g)}` }}</option>
          </select>
        </label>
        <label>
          Discipline
          <select data-action="discipline" :value="filter.discipline" @change="setFilter('discipline', ($event.target as HTMLSelectElement).value)">
            <option value="">all</option>
            <option v-for="d in disciplines" :key="d" :value="d">{{ d }}</option>
          </select>
        </label>
        <label>
          Status
          <select data-action="status" :value="filter.status" @change="setFilter('status', ($event.target as HTMLSelectElement).value)">
            <option value="">all</option>
            <option v-for="s in STATUSES" :key="s" :value="s">{{ statusLabel(s) }}</option>
            <option v-if="filter.closed" value="closed">closed</option>
          </select>
        </label>
        <label>
          <input type="checkbox" data-action="closed" :checked="filter.closed" @change="setFilter('closed', ($event.target as HTMLInputElement).checked ? '1' : '')" />
          closed items ({{ closedCount }})
        </label>
        <span class="faint">{{ shown.length }} shown</span>
      </div>

      <p v-if="!data.issues.length" class="muted">No issues carry the label {{ data.label }} yet.</p>
      <p v-else-if="!shown.length" class="muted">No issue matches the filter.</p>

      <section v-for="g in groups" :key="g.gate ?? 'none'" :aria-label="g.gate === null ? 'No gate' : `Before ${stageTitle(g.gate)}`" :data-gate="g.gate ?? 'none'">
        <h2>
          {{ g.gate === null ? "No gate" : `To close before ${stageTitle(g.gate)}` }}
          <span class="muted">{{ g.issues.length }}</span>
          <span v-if="g.gate && g.gate === data.stage" class="badge stage">current stage</span>
        </h2>
        <ul class="list">
          <li v-for="issue in g.issues" :key="issue.number" class="issue" :data-issue="issue.number" :class="{ closed: issue.state === 'closed' }">
            <div class="head">
              <a class="number" :href="issue.url" target="_blank" rel="noopener">#{{ issue.number }}</a>
              <span class="badge" :class="typeTone(issue.type)" :data-type="issue.type ?? 'untyped'">{{ typeLabel(issue.type) }}</span>
              <span class="title">{{ issue.title }}</span>
            </div>
            <div class="meta">
              <span class="badge" :class="{ warning: issue.status === 'for-verification', info: issue.status === 'in-progress' }" :data-status="issue.status">{{
                statusLabel(issue.status)
              }}</span>
              <span v-if="issue.waiting" class="badge warning" :data-waiting="issue.waiting">{{ waitingLabel(issue.waiting) }}</span>
              <span v-if="issue.disciplines.length" class="muted" data-disciplines>{{ issue.disciplines.join(", ") }}</span>
              <span v-if="issue.source" class="faint" data-source>from {{ issue.source }}</span>
              <span v-if="issue.gates.length > 1" class="faint" data-gates>gates {{ issue.gates.join(", ") }}</span>
              <span v-if="issue.gate && !data.stages.includes(issue.gate)" class="badge warning" data-unknown-gate title="Its gate: label names no stage of the plant, so it blocks every gate">not a stage of the plant</span>
            </div>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.summary {
  margin: var(--space-2) 0 var(--space-3);
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2) var(--space-3);
  margin: var(--space-2) 0;
}
.toolbar.new .btn:hover {
  text-decoration: none;
}
.filters label {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  min-width: 0;
}
.filters select {
  max-width: min(60vw, 260px);
}
h2 {
  font-size: var(--text);
  margin: var(--space-4) 0 var(--space-2);
}
.list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-2);
}
.issue {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  min-width: 0;
}
.issue.closed {
  opacity: 0.7;
}
.head,
.meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--space-1) var(--space-2);
  min-width: 0;
}
.meta {
  margin-top: var(--space-1);
  font-size: var(--text-sm);
}
.number {
  font-weight: 600;
}
.title {
  min-width: 0;
  overflow-wrap: anywhere;
}
</style>
