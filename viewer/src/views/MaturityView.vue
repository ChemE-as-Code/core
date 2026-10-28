<script setup lang="ts">
import { computed, watch } from "vue";
import type { MaturityLevel } from "@/api";
import FindingsList from "@/components/FindingsList.vue";
import JsonTree from "@/components/JsonTree.vue";
import { formatDate, pathSegments, shortRev } from "@/lib/format";
import {
  LEVEL_STATE_LABEL,
  MATURITY_FILE,
  PHASE_NOTE,
  REQUIREMENT_LABEL,
  levelName,
  levelReason,
  levelScope,
  levelState,
  maturityBadge,
  requirementClass,
  type LevelState,
} from "@/lib/maturity";
import { useRev } from "@/lib/useRev";
import { loadMaturity, maturity, store } from "@/store";

const { rev, withRev } = useRev();
// The header loads it too; this page also stands alone (embedded, phones).
watch(rev, (value) => void loadMaturity(value), { immediate: true });
const state = computed(() => maturity[rev.value ?? ""] ?? { kind: "loading" as const });
const badge = computed(() => maturityBadge(state.value));
const report = computed(() => (state.value.kind === "report" ? state.value : null));
const current = computed(() => report.value?.currency === "current");

const phaseTitle = computed(() => {
  const repo = store.repo;
  if (!repo?.stage) return null;
  return repo.stages.find((s) => s.id === repo.stage)?.title ?? repo.stage;
});

const ORIGIN_LABEL = {
  live: "GET /api/maturity: evaluated now on the working tree",
  snapshot: "the static snapshot's maturity report, evaluated on the working tree it was written from",
  recorded: `${MATURITY_FILE} as recorded at this revision (cheme maturity --write)`,
} as const;

const STATE_CLASS: Record<LevelState, string> = {
  achieved: "pass",
  "not-achieved": "",
  "not-assessable": "",
  "not-evaluated": "",
};
const STATE_MARK: Record<LevelState, string> = {
  achieved: "✓",
  "not-achieved": "✗",
  "not-assessable": "?",
  "not-evaluated": "–",
};

const levels = computed(() => {
  const all = report.value?.report.levels ?? [];
  return all.map((level: MaturityLevel, index) => ({
    level,
    index,
    name: levelName(level.id),
    scope: levelScope(level.id) ?? level.title,
    state: levelState(level),
    reason: levelReason(level, all),
  }));
});

const findings = computed(() =>
  (report.value?.report.findings ?? []).map((f) => ({ ...f, ids: [] })),
);

const artifactKinds = computed(() => Object.entries(report.value?.report.artifacts?.files ?? {}));
const claim = computed(() => report.value?.report.manifest ?? null);

/** A file link, or null for a directory (`pid/`) or no file. */
function fileTo(file: string, line?: number | null) {
  if (!file || file.endsWith("/")) return null;
  return { name: "file", params: { path: pathSegments(file) }, query: withRev(line ? { line: String(line) } : {}) };
}

function hasEvidence(value: Record<string, unknown> | null | undefined): boolean {
  return Boolean(value && Object.keys(value).length);
}

function reevaluate(): void {
  void loadMaturity(rev.value, true);
}
</script>

<template>
  <div class="page maturity-page">
    <h1>
      Maturity
      <small>{{ rev ? `at ${shortRev(rev)}` : store.snapshot ? "of the snapshot" : "of the working tree" }}</small>
    </h1>

    <!-- The two things the header shows, side by side and explained. -->
    <div class="axes">
      <section class="axis" aria-labelledby="phase-h">
        <h2 id="phase-h">Project phase <span class="muted">declared</span></h2>
        <p class="value">
          <span v-if="phaseTitle" class="badge stage" data-testid="phase-value">{{ phaseTitle }}</span>
          <span v-else class="muted">No stage declared in plant.yaml.</span>
        </p>
        <p class="muted small">{{ PHASE_NOTE }} A stage sign-off does not raise the calculation maturity.</p>
      </section>
      <section class="axis" aria-labelledby="maturity-h">
        <h2 id="maturity-h">Verified maturity <span class="muted">evidence-based</span></h2>
        <p class="value">
          <span class="badge" :class="badge.tone" data-testid="maturity-value">{{ badge.value }}</span>
        </p>
        <p class="muted small">
          The highest of four cumulative calculation-maturity levels whose requirements all pass in core's
          <code>cheme maturity</code> report. Artifact completeness and independent review are separate, below.
        </p>
      </section>
    </div>

    <p v-if="state.kind === 'loading'" class="muted" aria-live="polite">
      {{ rev || store.snapshot ? "Reading the maturity report…" : "Evaluating the maturity of the working tree (cheme maturity; this can take half a minute on a large plant)…" }}
    </p>
    <div v-else-if="state.kind === 'missing'" class="notice" role="status" data-testid="maturity-missing">
      <strong>No maturity report.</strong> {{ state.message }} Nothing is shown as achieved.
    </div>
    <div v-else-if="state.kind === 'incompatible'" class="notice warning" role="status" data-testid="maturity-incompatible">
      <strong>Incompatible maturity report.</strong> It has schema <code>{{ state.schema }}</code>; this viewer reads
      <code>cheme/maturity-report/v1</code>. Nothing is shown as achieved.
    </div>
    <div v-else-if="state.kind === 'error'" class="notice error" role="alert">
      The maturity report could not be loaded: {{ state.message }}
      <button v-if="!rev && !store.snapshot" class="btn retry" type="button" @click="reevaluate">Retry</button>
    </div>

    <template v-if="report">
      <div v-if="report.currency === 'stale'" class="notice warning" role="status" data-testid="maturity-stale">
        <strong>Outdated report.</strong> {{ MATURITY_FILE }} at this revision was recorded for other inputs: changed since
        <code v-for="p in report.inputs?.changed ?? []" :key="p" class="path">{{ p }}</code>. It is shown below as recorded, not as
        the maturity of this revision; run <code>cheme maturity --write</code> to record it again.
      </div>
      <div v-else-if="report.currency === 'unverified'" class="notice warning" role="status" data-testid="maturity-unverified">
        <strong>Unconfirmed report.</strong> The inputs {{ MATURITY_FILE }} recorded could not be compared with this revision<template
          v-if="report.inputs?.unreadable.length"
          >
          (cannot read <code v-for="p in report.inputs.unreadable" :key="p" class="path">{{ p }}</code>)</template
        ><template v-else-if="!report.inputs?.matching.length"> (it records no input fingerprints)</template>. It is shown below as
        recorded, not as the maturity of this revision.
      </div>
      <div v-if="report.report.source?.dirty?.length" class="notice info" role="status" data-testid="maturity-dirty">
        Evaluated with uncommitted changes to
        <code v-for="p in report.report.source.dirty" :key="p" class="path">{{ p }}</code>: commit
        {{ report.report.source.commit ? shortRev(report.report.source.commit) : "(none)" }} alone does not identify its inputs.
      </div>
      <div v-if="claim?.claim_exceeds_evidence" class="notice warning" role="status" data-testid="maturity-claim">
        <strong>Claim exceeds evidence.</strong> {{ claim.file }} claims library maturity
        <code>{{ String(claim.claimed_maturity) }}</code>; the evidence supports <code v-if="claim.supported_maturity">{{ claim.supported_maturity }}</code><template v-else>no level</template>.
      </div>
      <div v-else-if="claim?.claim_exceeds_evidence === null && claim.claimed_maturity" class="notice" role="status">
        {{ claim.file }} claims library maturity <code>{{ String(claim.claimed_maturity) }}</code>; not decided by this report (evaluated through
        {{ levelName(report.report.evaluated_through) }}).
      </div>

      <section aria-labelledby="provenance-h">
        <h2 id="provenance-h">Report</h2>
        <dl class="facts">
          <dt>Source</dt>
          <dd>
            {{ ORIGIN_LABEL[report.origin] }}
            <RouterLink v-if="report.origin === 'recorded'" :to="fileTo(MATURITY_FILE)!">{{ MATURITY_FILE }}</RouterLink>
            <button v-if="report.origin === 'live'" class="btn" type="button" @click="reevaluate">Evaluate again</button>
          </dd>
          <dt>Checked</dt>
          <dd>{{ report.report.checked_at ? formatDate(report.report.checked_at) : "not recorded" }}</dd>
          <dt>Core version</dt>
          <dd><code>{{ report.report.core_version || "unknown" }}</code></dd>
          <dt>Inputs at commit</dt>
          <dd>
            <template v-if="report.report.source?.commit">
              <RouterLink v-if="!store.snapshot" :to="{ name: 'home', query: { rev: report.report.source.commit } }"><code>{{ shortRev(report.report.source.commit) }}</code></RouterLink>
              <code v-else>{{ shortRev(report.report.source.commit) }}</code>
              {{ report.report.source.dirty?.length ? "with uncommitted changes" : "" }}
            </template>
            <span v-else class="muted">unknown (not a git repository, or no commit)</span>
          </dd>
          <dt>Evaluated through</dt>
          <dd>{{ levelName(report.report.evaluated_through) }}</dd>
        </dl>
        <details v-if="Object.keys(report.report.source?.fingerprints ?? {}).length" class="inputs">
          <summary>Input fingerprints ({{ Object.keys(report.report.source.fingerprints).length }})</summary>
          <div class="table-wrap">
            <table class="data">
              <thead><tr><th>input</th><th>fingerprint</th><th v-if="report.inputs">at this revision</th></tr></thead>
              <tbody>
                <tr v-for="(fp, path) in report.report.source.fingerprints" :key="path">
                  <td><code>{{ path }}</code></td>
                  <td><code class="faint">{{ fp.slice(0, 19) }}…</code></td>
                  <td v-if="report.inputs">
                    {{ report.inputs.matching.includes(String(path)) ? "matches" : report.inputs.changed.includes(String(path)) ? "changed" : "not compared" }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </details>
      </section>

      <section aria-labelledby="levels-h">
        <h2 id="levels-h">
          Calculation maturity levels
          <span v-if="!current" class="badge warning">as recorded, not current</span>
        </h2>
        <ol class="levels">
          <li v-for="l in levels" :key="l.level.id" :class="{ outdated: !current }" :data-level="l.level.id" :data-state="l.state">
            <h3 :id="`level-${l.level.id}`">
              <span class="badge" :class="current ? STATE_CLASS[l.state] : ''" data-testid="level-state">
                <span v-if="current" aria-hidden="true">{{ STATE_MARK[l.state] }}</span> {{ LEVEL_STATE_LABEL[l.state] }}{{ current ? "" : " (as recorded, not current)" }}
              </span>
              {{ l.index + 1 }}. {{ l.name }}
              <span class="muted scope">{{ l.scope }}</span>
            </h3>
            <p class="muted small">
              {{ l.reason }} Supports library maturity up to <code>{{ l.level.library_maturity }}</code>.
            </p>
            <details v-if="l.level.requirements.length" :open="l.state !== 'achieved' && current">
              <summary>Requirements ({{ l.level.requirements.length }})</summary>
              <div class="table-wrap">
                <table class="data" :aria-labelledby="`level-${l.level.id}`">
                  <thead><tr><th>status</th><th>requirement</th><th>file</th><th>detail</th></tr></thead>
                  <tbody>
                    <tr v-for="r in l.level.requirements" :key="r.id" :data-requirement="r.id">
                      <td><span class="badge" :class="current ? requirementClass(r.status) : ''">{{ REQUIREMENT_LABEL[r.status] ?? r.status }}</span></td>
                      <td>
                        <code>{{ r.id }}</code>
                        <div>{{ r.title }}</div>
                        <span v-if="!r.required" class="muted small">not required</span>
                      </td>
                      <td>
                        <RouterLink v-if="fileTo(r.file, r.line)" :to="fileTo(r.file, r.line)!">{{ r.file }}<template v-if="r.line">:{{ r.line }}</template></RouterLink>
                        <code v-else-if="r.file">{{ r.file }}</code>
                      </td>
                      <td class="detail">
                        <div v-if="r.detail">{{ r.detail }}</div>
                        <div v-if="r.hint && r.status !== 'pass'" class="muted small">{{ r.hint }}</div>
                        <details v-if="hasEvidence(r.evidence)" class="evidence">
                          <summary>Evidence</summary>
                          <JsonTree :value="r.evidence" />
                        </details>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </details>
          </li>
        </ol>
      </section>

      <section v-if="report.report.limitations?.length" aria-labelledby="limitations-h">
        <h2 id="limitations-h">Limitations <span class="muted">{{ report.report.limitations.length }}</span></h2>
        <ul class="plain">
          <li v-for="(l, i) in report.report.limitations" :key="i">
            <code>{{ l.subject }}</code> {{ l.limitation }}
            <RouterLink v-if="fileTo(l.file, l.line)" class="faint" :to="fileTo(l.file, l.line)!">{{ l.file }}<template v-if="l.line">:{{ l.line }}</template></RouterLink>
          </li>
        </ul>
      </section>

      <section v-if="report.report.model_basis?.length" aria-labelledby="basis-h">
        <h2 id="basis-h">Model basis of reactors and separators</h2>
        <div class="table-wrap">
          <table class="data">
            <thead><tr><th>unit</th><th>role</th><th>basis</th><th>predictive</th><th>sourced</th><th>simulated</th><th>detail</th></tr></thead>
            <tbody>
              <tr v-for="u in report.report.model_basis" :key="u.id">
                <td><RouterLink v-if="fileTo(u.file, u.line)" :to="fileTo(u.file, u.line)!">{{ u.id }}</RouterLink><template v-else>{{ u.id }}</template></td>
                <td>{{ u.role }}</td>
                <td><code>{{ u.basis }}</code></td>
                <td>{{ u.predictive ? "yes" : "no" }}</td>
                <td>{{ u.sourced ? "yes" : "no" }}</td>
                <td>{{ u.simulated ? "yes" : "no" }}</td>
                <td class="detail">{{ u.detail }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="report.report.assumptions" aria-labelledby="assumptions-h">
        <h2 id="assumptions-h">Assumptions</h2>
        <ul class="plain">
          <li v-for="(a, i) in report.report.assumptions.design_basis ?? []" :key="`db${i}`">{{ a }} <span class="faint">(design basis)</span></li>
          <li v-for="(n, file) in report.report.assumptions.assumed_values ?? {}" :key="file">
            {{ n }} assumed value{{ n === 1 ? "" : "s" }} in <RouterLink :to="fileTo(String(file))!">{{ file }}</RouterLink>
          </li>
        </ul>
      </section>

      <div class="axes">
        <section class="axis" aria-labelledby="artifacts-h" data-testid="maturity-artifacts">
          <h2 id="artifacts-h">Artifact completeness</h2>
          <p class="muted small">Which deliverables exist; {{ report.report.artifacts?.note ?? "artifact completeness never establishes calculation maturity" }}.</p>
          <ul class="plain">
            <li v-for="[kind, files] in artifactKinds" :key="kind">
              <span class="badge" :class="files.length ? 'info' : ''">{{ files.length ? `${files.length} found` : "none" }}</span>
              {{ kind.replace(/_/g, " ") }}
            </li>
            <li v-if="report.report.artifacts?.sheets?.length">
              <span class="badge info">{{ report.report.artifacts.sheets.filter((s) => s.exists).length }} / {{ report.report.artifacts.sheets.length }}</span>
              declared sheets drawn
            </li>
          </ul>
        </section>
        <section class="axis" aria-labelledby="review-h" data-testid="maturity-review">
          <h2 id="review-h">Independent review</h2>
          <p class="muted small">Set by people only; {{ report.report.review?.note ?? "cheme maturity reads it and never writes it" }}. Passing checks are not a review.</p>
          <p>
            Manifest review status:
            <code>{{ report.report.review?.manifest_status ?? "none" }}</code>
          </p>
          <p>
            {{ report.report.review?.records?.length ?? 0 }} review record{{ report.report.review?.records?.length === 1 ? "" : "s" }}
            <RouterLink :to="{ name: 'reviews', query: withRev() }">(Reviews)</RouterLink>
          </p>
        </section>
      </div>

      <FindingsList :findings="findings" label="Maturity findings" title="Findings" />
    </template>
  </div>
</template>

<style scoped>
.axes {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--space-3);
  margin: var(--space-3) 0;
}
.axis {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--space-3);
  background: var(--surface);
  min-width: 0;
}
.axis h2,
section > h2 {
  font-size: var(--text);
  margin: 0 0 var(--space-2);
  display: flex;
  gap: var(--space-2);
  align-items: center;
  flex-wrap: wrap;
}
section > h2 {
  margin-top: var(--space-4);
}
.value {
  margin: 0 0 var(--space-2);
}
.small {
  font-size: var(--text-sm);
}
.path {
  margin: 0 0.25em;
}
.retry {
  margin-left: var(--space-2);
}
.levels {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.levels > li {
  border: 1px solid var(--border);
  border-left-width: 4px;
  border-radius: var(--radius);
  padding: var(--space-2) var(--space-3);
  min-width: 0;
}
.levels > li[data-state="achieved"]:not(.outdated) {
  border-left-color: var(--ok);
}
.levels h3 {
  font-size: var(--text);
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: baseline;
}
.scope {
  font-weight: 400;
  font-size: var(--text-sm);
}
.detail {
  min-width: 220px;
  overflow-wrap: anywhere;
}
.evidence summary {
  font-weight: 400;
  font-size: var(--text-sm);
}
.plain {
  margin: 0;
  padding-left: var(--space-4);
  font-size: var(--text-sm);
  overflow-wrap: anywhere;
}
.facts {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--space-2) var(--space-4);
  margin: 0 0 var(--space-3);
}
.facts dt {
  color: var(--fg-muted);
}
.facts dd {
  margin: 0;
  min-width: 0;
  overflow-wrap: anywhere;
}
.facts .btn {
  margin-left: var(--space-2);
}
</style>
