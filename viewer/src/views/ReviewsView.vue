<script setup lang="ts">
import SectionBar from "@/components/SectionBar.vue";
import { computed, onMounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, ApiError } from "@/api";
import LoadState from "@/components/LoadState.vue";
import MarkdownRender from "@/components/MarkdownRender";
import SignoffStrip from "@/components/SignoffStrip.vue";
import { loadStatus, store } from "@/store";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { pathSegments, shortRev } from "@/lib/format";
import {
  BLOCKING,
  filterRegister,
  findingMarkdown,
  isRecordPath,
  openFindings,
  parseRecord,
  register,
  severityCounts,
  sortRecords,
  summarizeRecords,
  type ReviewRecord,
} from "@/lib/reviews";

const route = useRoute();
const router = useRouter();
const { rev, withRev } = useRev();

/** The records at `rev`, read as files (front matter, finding tables). */
const records = useAsync<ReviewRecord[]>(async (signal) => {
  const tree = await api.tree(rev.value, signal);
  const paths = tree.filter((e) => e.type === "file" && isRecordPath(e.path)).map((e) => e.path);
  const texts = await Promise.all(
    paths.map((path) =>
      api.file(path, rev.value, signal).catch((error: unknown) => {
        // a record above a snapshot's size limit: listed, without its tables
        if (error instanceof ApiError && error.status === 404) return "";
        throw error;
      }),
    ),
  );
  return sortRecords(paths.map((path, i) => parseRecord(path, texts[i] ?? "")));
}, rev);

onMounted(() => {
  if (!rev.value) void loadStatus();
});

/** The server's list (working tree only), else the one derived from the records. */
const serverOpen = computed(() => (!rev.value ? (store.status?.reviews.open ?? null) : null));
const open = computed(() => serverOpen.value ?? openFindings(records.data.value ?? []));
const rows = computed(() => register(open.value, records.data.value ?? []));
const summaries = computed(() => summarizeRecords(records.data.value ?? [], serverOpen.value ?? undefined));
const blockingCount = computed(() => rows.value.filter((r) => r.blocking).length);
const counts = computed(() => severityCounts(open.value));

const first = (v: unknown) => (Array.isArray(v) ? v[0] : v);
const severity = computed(() => String(first(route.query.severity) ?? ""));
const recordFilter = computed(() => String(first(route.query.record) ?? ""));
const shown = computed(() => filterRegister(rows.value, { severity: severity.value, record: recordFilter.value }));
/** Records that raised an open finding, for the record filter. */
const originRecords = computed(() => {
  const set = new Set(rows.value.map((r) => r.origin).filter((p): p is string => Boolean(p)));
  return summaries.value.filter((s) => set.has(s.record.path)).map((s) => s.record);
});

function setFilter(key: "severity" | "record", value: string): void {
  const query = { ...route.query };
  if (value) query[key] = value;
  else delete query[key];
  void router.replace({ query });
}

const fileLink = (path: string) => ({ name: "file", params: { path: pathSegments(path) }, query: withRev() });
const stemOfPath = (path: string) => path.replace(/^reviews\//, "").replace(/\.md$/, "");

const source = computed(() => {
  if (serverOpen.value) return "from cheme status of the working tree";
  if (rev.value) return `derived from the records at ${shortRev(rev.value)}`;
  if (store.statusLoading) return "derived from the records (cheme status is still running)";
  return "derived from the records";
});

function refresh(): void {
  void records.reload();
  if (!rev.value) void loadStatus(true);
}
</script>

<template>
  <div class="page">
    <h1>Reviews <small>{{ rev ? shortRev(rev) : "working tree" }}</small></h1>

    <SignoffStrip class="block" />

    <div class="toolbar summary" aria-label="Summary">
      <span class="badge" :class="open.length ? 'warning' : 'pass'" data-testid="open-count">{{ open.length }} open</span>
      <span class="badge" :class="blockingCount ? 'fail' : 'pass'" data-testid="blocking-count" :title="`Open ${[...BLOCKING].join(', ')} findings block a sign-off`">{{ blockingCount }} blocking</span>
      <span v-for="c in counts" :key="c.severity" class="badge sev" :data-severity="c.severity || 'none'">{{ c.count }} {{ c.severity || "no severity" }}</span>
      <span class="faint">in {{ records.data.value?.length ?? store.status?.reviews.records ?? 0 }} records</span>
      <span class="spacer" />
      <button class="btn" type="button" :disabled="records.loading.value || store.statusLoading" @click="refresh">Refresh</button>
    </div>
    <p class="muted hint">Open findings {{ source }}. A finding is open until a later record lists it as closed, accepted or superseded.</p>
    <p v-if="!rev && store.statusError" class="muted hint" data-testid="status-note">{{ store.statusError }} The register is derived from the records.</p>

    <LoadState :loading="records.loading.value && !records.data.value" :error="records.error.value" @retry="records.reload" />

    <template v-if="records.data.value">
      <!-- two sections, but the open findings run long: the records are a click away -->
      <SectionBar :min="2" />
      <section aria-label="Open findings">
        <h2>Open findings</h2>
        <div class="toolbar filters">
          <label>
            Severity
            <select data-action="severity" :value="severity" @change="setFilter('severity', ($event.target as HTMLSelectElement).value)">
              <option value="">all</option>
              <option value="blocking">blocking ({{ [...BLOCKING].join(", ") }})</option>
              <option v-for="c in counts" :key="c.severity" :value="c.severity">{{ c.severity || "no severity" }} ({{ c.count }})</option>
            </select>
          </label>
          <label>
            Raised in
            <select data-action="record" :value="recordFilter" @change="setFilter('record', ($event.target as HTMLSelectElement).value)">
              <option value="">all records</option>
              <option v-for="r in originRecords" :key="r.path" :value="r.path">{{ r.stem }}</option>
            </select>
          </label>
          <span class="faint">{{ shown.length }} of {{ rows.length }}</span>
        </div>
        <p v-if="!rows.length" class="muted">No open review findings.</p>
        <p v-else-if="!shown.length" class="muted">No open finding matches the filter.</p>
        <ul class="register">
          <li v-for="f in shown" :key="f.id" class="finding" :data-finding="f.id" :class="{ blocking: f.blocking }">
            <div class="head">
              <code class="id">{{ f.id }}</code>
              <span class="badge sev" :data-severity="f.severity || 'none'">{{ f.severity || "no severity" }}</span>
              <span v-if="f.blocking" class="badge fail" title="Blocks a stage sign-off while open">blocking</span>
            </div>
            <div class="text">
              <MarkdownRender :source="findingMarkdown(f.finding)" :path="f.record" :rev="rev" :heading-ids="false" />
            </div>
            <div class="links">
              <span v-if="f.origin">raised in <RouterLink :to="fileLink(f.origin)">{{ stemOfPath(f.origin) }}</RouterLink></span>
              <span v-if="f.record !== f.origin">listed open in <RouterLink :to="fileLink(f.record)">{{ stemOfPath(f.record) }}</RouterLink></span>
              <span v-if="f.reviewedCommit">
                reviewed at
                <RouterLink v-if="!store.snapshot" :to="{ name: 'home', query: { rev: f.reviewedCommit } }" :title="`Show the plant at ${f.reviewedCommit}`"><code>{{ f.reviewedCommit.slice(0, 7) }}</code></RouterLink>
                <code v-else>{{ f.reviewedCommit.slice(0, 7) }}</code>
              </span>
            </div>
          </li>
        </ul>
      </section>

      <section aria-label="Records">
        <h2>Records</h2>
        <p v-if="!summaries.length" class="muted">No review records in reviews/.</p>
        <div v-else class="table-wrap">
          <table class="data records">
            <thead>
              <tr>
                <th>Record</th>
                <th>Topic</th>
                <th>Reviewer</th>
                <th>Reviewed</th>
                <th title="Findings it raised">Raised</th>
                <th>Open</th>
                <th>Closed</th>
                <th>Accepted</th>
                <th>Superseded</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in summaries" :key="s.record.path" :data-record="s.record.stem">
                <td><RouterLink :to="fileLink(s.record.path)">{{ s.record.stem }}</RouterLink></td>
                <td>{{ s.record.front?.topic ?? "" }}<span v-if="!s.record.front" class="badge" title="No front matter: no kind: review gate accepts it">no front matter</span></td>
                <td>
                  {{ s.record.front?.reviewer ?? "" }}
                  <span v-if="s.record.front?.reviewer_kind" class="badge" :class="{ info: s.record.front.reviewer_kind === 'human' }">{{ s.record.front.reviewer_kind }}</span>
                </td>
                <td>
                  <template v-if="s.record.front?.reviewed_commit">
                    <RouterLink v-if="!store.snapshot" :to="{ name: 'home', query: { rev: s.record.front.reviewed_commit } }"><code>{{ s.record.front.reviewed_commit.slice(0, 7) }}</code></RouterLink>
                    <code v-else>{{ s.record.front.reviewed_commit.slice(0, 7) }}</code>
                  </template>
                </td>
                <td class="num">{{ s.raised }}</td>
                <td class="num" data-col="open">
                  <a v-if="s.open" href="#" @click.prevent="setFilter('record', s.record.path)">{{ s.open }}</a><template v-else>0</template>
                  <span v-if="s.blocking" class="badge fail">{{ s.blocking }} blocking</span>
                </td>
                <td class="num" data-col="closed">{{ s.closed }}</td>
                <td class="num" data-col="accepted">{{ s.accepted }}</td>
                <td class="num">{{ s.superseded }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.block {
  margin-bottom: var(--space-4);
}
.hint {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
}
h2 {
  font-size: var(--text);
  margin: var(--space-4) 0 var(--space-2);
}
.filters label {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  min-width: 0;
}
.filters select {
  max-width: min(60vw, 320px);
}
.badge.sev[data-severity="critical"],
.badge.sev[data-severity="high"],
.badge.sev[data-severity="major"] {
  background: var(--bad-soft);
  color: var(--bad);
}
.badge.sev[data-severity="medium"],
.badge.sev[data-severity="minor"] {
  background: var(--warn-soft);
  color: var(--warn);
}
.badge.sev[data-severity="low"],
.badge.sev[data-severity="info"],
.badge.sev[data-severity="note"] {
  background: var(--info-soft);
  color: var(--info);
}
.register {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.finding {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  padding: var(--space-2) var(--space-3);
  min-width: 0;
}
.finding.blocking {
  border-left: 3px solid var(--bad);
}
.head {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: center;
}
.id {
  font-weight: 600;
  overflow-wrap: anywhere;
}
.text {
  overflow-wrap: anywhere;
  line-height: 1.5;
}
.text :deep(p),
.text :deep(ul),
.text :deep(ol) {
  margin: var(--space-1) 0;
}
.text :deep(code) {
  background: var(--bg-sunk);
  padding: 0 3px;
  border-radius: 3px;
}
.links {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-3);
  font-size: var(--text-sm);
  color: var(--fg-muted);
}
.records td.num {
  white-space: nowrap;
}
.records td.num .badge {
  margin-left: var(--space-1);
}
</style>
