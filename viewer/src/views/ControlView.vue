<script setup lang="ts">
import { computed } from "vue";
import { api, ApiError, type ControlReport } from "@/api";
import FindingsList from "@/components/FindingsList.vue";
import LoadState from "@/components/LoadState.vue";
import { store, useIssues } from "@/store";
import { newIssueUrl } from "@/lib/issues";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { pathSegments, shortRev } from "@/lib/format";
import { countsText, fileStatus, findingsOf, KIND_LABEL, statusTone, worstLevel } from "@/lib/control";

const { rev } = useRev();

/** The report, or null when the plant has no control records (a 404). */
async function load(signal: AbortSignal): Promise<ControlReport | null> {
  try {
    return await api.control(signal);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

const report = useAsync((signal) => load(signal));
const data = computed(() => report.data.value ?? null);
const missing = computed(() => !report.loading.value && !report.error.value && report.data.value === null);
const narrative = computed(() => data.value?.documents.find((d) => d.kind === "narrative") ?? null);
const philosophy = computed(() => data.value?.documents.find((d) => d.kind === "philosophy") ?? null);

/** The page shows the working tree, so its links do too (never `?rev=`). */
function fileLink(path: string) {
  return { name: "file", params: { path: pathSegments(path) } };
}
function status(path: string) {
  return data.value ? fileStatus(data.value.files, path) : undefined;
}
const LOOPS = "control/loops.yaml";
const SEQUENCES = "control/sequences.yaml";
const issues = useIssues();
/** "New issue about <loop>": the action-item form with the loop in its References. */
const loopIssue = (id: string) => newIssueUrl(issues.value, { refs: `${LOOPS} ${id}` });
const yesNo = (value: boolean | null, yes: string, no: string) => (value === null ? "?" : value ? yes : no);
</script>

<template>
  <div class="page control">
    <h1>
      Control
      <small>loops, sequences, narrative and control philosophy in the working tree</small>
    </h1>
    <p v-if="rev" class="notice warning" data-control-rev>
      This page shows the working tree (review status needs the repository's history), not {{ shortRev(rev) }}.
    </p>

    <LoadState :loading="report.loading.value && !data" :error="report.error.value" @retry="report.reload" />
    <div v-if="missing" class="notice" data-control-missing>
      <p v-if="store.snapshot && store.repo?.has_control" data-control-not-exported>
        <strong>This snapshot does not hold the control report.</strong>
        The plant has control records, but <code>cheme export-static</code> records them only for the working tree without
        <code>--exclude</code> (the report names reviewers). Open the files in the file tree.
      </p>
      <p v-else><strong>No control records.</strong></p>
      <p class="muted">
        The page shows <code>control/loops.yaml</code>, <code>control/sequences.yaml</code>, <code>process/narrative.md</code> and
        <code>control/philosophy.md</code> once the plant fills them in (skills <code>control-loops</code>, <code>control-sequences</code>,
        <code>control-narrative</code>; <code>cheme control report</code>). The empty templates of <code>cheme init</code> do not count.

      </p>
    </div>

    <template v-if="data">
      <p class="muted">
        Proposed control intent, not an implementation. The status of each file comes from the review records:
        <em>drafted</em> (no current review), <em>reviewed</em>, <em>accepted</em> (a human review with no blocking finding open).
        Source {{ data.source.commit ? shortRev(data.source.commit) : "not committed" }}<template v-if="data.source.dirty.length">, uncommitted: {{ data.source.dirty.join(", ") }}</template>.
      </p>

      <section aria-label="Files">
        <h2>Files</h2>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr><th scope="col">File</th><th scope="col">Status</th><th scope="col">Why</th><th scope="col">Findings</th></tr>
            </thead>
            <tbody>
              <tr v-for="f in data.files" :key="f.path" :data-file="f.path">
                <td>
                  <RouterLink :to="fileLink(f.path)">{{ f.path }}</RouterLink>
                  <span class="faint kind">{{ KIND_LABEL[f.kind] }}</span>
                </td>
                <td><span class="badge" :class="statusTone(f.status)" :data-status="f.status">{{ f.status }}</span></td>
                <td class="muted">
                  <RouterLink v-if="f.record" :to="fileLink(f.record)">{{ f.detail }}</RouterLink>
                  <template v-else>{{ f.detail }}</template>
                </td>
                <td>{{ findingsOf(data.findings, f.path).length || "–" }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="data.loops.length" aria-label="Loops">
        <h2>
          Loops <span class="muted">{{ data.loops.length }}</span>
          <span v-if="status(LOOPS)" class="badge" :class="statusTone(status(LOOPS)!.status)">{{ status(LOOPS)!.status }}</span>
        </h2>
        <p class="muted">action: direct (the output rises with the measurement) or reverse; fail: the position on loss of signal, power or air; ? not known yet.</p>
        <div class="table-wrap">
          <table class="data loops">
            <thead>
              <tr>
                <th scope="col">Loop</th>
                <th scope="col">Measures</th>
                <th scope="col">Controller</th>
                <th scope="col">Action</th>
                <th scope="col">Moves</th>
                <th scope="col">Targets</th>
                <th scope="col">Modes</th>
                <th scope="col">Links, trips</th>
                <th scope="col">Alarms</th>
                <th scope="col">Open</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="loop in data.loops" :key="loop.id" :data-loop="loop.id">
                <th scope="row">
                  <strong>{{ loop.id }}</strong>
                  <span class="title">{{ loop.title }}</span>
                  <span v-if="loop.section" class="faint">{{ loop.section }}</span>
                  <a v-if="loopIssue(loop.id)" class="new-issue" :href="loopIssue(loop.id)!" target="_blank" rel="noopener" data-action="new-issue">New issue about {{ loop.id }}</a>
                </th>
                <td>{{ loop.variable ?? "?" }}: {{ loop.measurement.join(", ") || "?" }}</td>
                <td>{{ loop.controller ?? "–" }}</td>
                <td>{{ loop.action ?? "?" }}</td>
                <td>{{ loop.final_elements.join("; ") || "–" }}</td>
                <td>{{ loop.targets.join("; ") || "?" }}</td>
                <td>{{ loop.modes.join(", ") || "?" }}<template v-if="loop.normal_mode"> (normal {{ loop.normal_mode }})</template></td>
                <td>
                  {{ loop.links.join("; ") }}
                  <template v-if="loop.interlocks.length">
                    <RouterLink :to="{ name: 'cause-effect' }">C&amp;E {{ loop.interlocks.join(", ") }}</RouterLink>
                  </template>
                </td>
                <td>
                  <span v-for="alarm in loop.alarms" :key="alarm" class="unresolved">{{ alarm }}</span>
                </td>
                <td>
                  <span v-if="worstLevel(loop.findings)" class="badge" :class="worstLevel(loop.findings)!">{{ countsText(loop.findings) }}</span>
                  <span v-for="item in loop.unresolved" :key="item" class="muted unresolved">{{ item }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="data.sequences.length" aria-label="Sequences">
        <h2>
          Sequences <span class="muted">{{ data.sequences.length }}</span>
          <span v-if="status(SEQUENCES)" class="badge" :class="statusTone(status(SEQUENCES)!.status)">{{ status(SEQUENCES)!.status }}</span>
        </h2>
        <article v-for="seq in data.sequences" :key="seq.id" class="sequence" :data-sequence="seq.id">
          <h3>
            {{ seq.id }} {{ seq.title }}
            <span class="badge info">{{ seq.mode }}</span>
            <span v-if="worstLevel(seq.findings)" class="badge" :class="worstLevel(seq.findings)!">{{ countsText(seq.findings) }}</span>
          </h3>
          <p v-if="seq.interlocks.length" class="muted">Trips (C&amp;E): {{ seq.interlocks.join(", ") }}</p>
          <template v-if="seq.permissives.length">
            <p>Start permissives:</p>
            <ul>
              <li v-for="p in seq.permissives" :key="p">{{ p }}</li>
            </ul>
          </template>
          <div class="table-wrap">
            <table class="data">
              <thead>
                <tr>
                  <th scope="col">Step</th>
                  <th scope="col">Entry</th>
                  <th scope="col">Actions</th>
                  <th scope="col">Complete when</th>
                  <th scope="col">Timeout</th>
                  <th scope="col">Next</th>
                  <th scope="col">Operator</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="step in seq.steps" :key="step.id">
                  <th scope="row">{{ step.id }} <span class="title">{{ step.title }}</span></th>
                  <td>{{ step.entry }}</td>
                  <td>{{ step.actions.join("; ") }}</td>
                  <td>{{ step.complete || "?" }}</td>
                  <td>{{ step.timeout }}</td>
                  <td>{{ step.next }}</td>
                  <td class="muted">{{ step.operator }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="seq.abort">
            Abort: {{ seq.abort.condition || "on a trip or by the operator" }}<template v-if="seq.abort.actions.length">; {{ seq.abort.actions.join("; ") }}</template
            ><template v-if="seq.abort.then">; then {{ seq.abort.then }}</template><template v-if="seq.abort.notes"> ({{ seq.abort.notes }})</template>
          </p>
          <p v-else class="muted">Abort: not stated.</p>
          <p v-if="seq.reset">
            Reset: {{ yesNo(seq.reset.latching, "latching", "not latching") }}, {{ yesNo(seq.reset.manual, "manual", "automatic") }}<template v-if="seq.reset.condition">, when {{ seq.reset.condition }}</template
            ><template v-if="seq.reset.restart">; restart when {{ seq.reset.restart }}</template>
          </p>
          <p v-for="item in seq.unresolved" :key="item" class="muted">Open: {{ item }}</p>
        </article>
      </section>

      <section v-if="narrative" aria-label="Process narrative">
        <h2>
          Process narrative
          <RouterLink :to="fileLink(narrative.path)">{{ narrative.path }}</RouterLink>
        </h2>
        <p v-if="!narrative.valid" class="notice warning">Its front matter does not load; see the findings.</p>
        <ul v-if="narrative.sections?.length">
          <li v-for="s in narrative.sections" :key="s.id">
            <strong>{{ s.id }}</strong> {{ s.title }}
            <span v-if="s.loops?.length" class="muted"> loops {{ s.loops.join(", ") }}</span>
            <span v-if="s.sequences?.length" class="muted"> sequences {{ s.sequences.join(", ") }}</span>
          </li>
        </ul>
        <p v-for="item in narrative.unresolved ?? []" :key="item" class="muted">Open: {{ item }}</p>
      </section>

      <section v-if="philosophy" aria-label="Control philosophy">
        <h2>
          Control philosophy
          <RouterLink :to="fileLink(philosophy.path)">{{ philosophy.path }}</RouterLink>
        </h2>
        <p v-if="!philosophy.valid" class="notice warning">Its front matter does not load; see the findings.</p>
        <template v-if="philosophy.objectives?.length">
          <p>Objectives:</p>
          <ul>
            <li v-for="o in philosophy.objectives" :key="o.id"><strong>{{ o.id }}</strong> {{ o.title }}</li>
          </ul>
        </template>
        <template v-if="philosophy.failures?.length">
          <p>Failures:</p>
          <ul>
            <li v-for="f in philosophy.failures" :key="f.id"><strong>{{ f.id }}</strong> {{ f.title }}<span v-if="f.response" class="muted">: {{ f.response }}</span></li>
          </ul>
        </template>
        <p v-for="item in philosophy.unresolved ?? []" :key="item" class="muted">Open: {{ item }}</p>
      </section>

      <FindingsList :findings="data.findings" label="Findings" :at-rev="false" />
      <p v-if="!data.findings.length" class="muted">No findings.</p>
    </template>
  </div>
</template>

<style scoped>
.title {
  display: block;
  font-weight: normal;
}
.unresolved {
  display: block;
}
.new-issue {
  display: block;
  font-weight: normal;
  font-size: var(--text-sm);
}
.kind {
  margin-left: var(--space-2);
}
.sequence {
  margin: var(--space-4) 0;
}
.sequence h3 {
  font-size: var(--text-md, 15px);
  margin: var(--space-2) 0;
}
table.loops td {
  min-width: 8em;
}
</style>
