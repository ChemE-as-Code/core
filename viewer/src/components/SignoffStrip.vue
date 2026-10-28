<script setup lang="ts">
import { computed, onMounted } from "vue";
import { api, ApiError, type StageSignoff } from "@/api";
import { loadStatus, store } from "@/store";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { pathSegments } from "@/lib/format";
import { signoffsFromStatusFile } from "@/lib/reviews";

/**
 * One chip per stage of plant.yaml: who signed it off, when, which commit, and the review record
 * it names. The working tree's come from `/api/status` (which also says whether the commit is
 * on the default branch); a revision, a snapshot or an older server read `checks/status.json`.
 */
const { rev, withRev } = useRev();

const statusFile = useAsync<string | null>(async (signal) => {
  try {
    return await api.file("checks/status.json", rev.value, signal);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}, rev);

onMounted(() => {
  if (!rev.value) void loadStatus();
});

const fromServer = computed(() => !rev.value && store.status !== null);
const signoffs = computed<Record<string, StageSignoff>>(() =>
  fromServer.value ? store.status!.signoffs : signoffsFromStatusFile(statusFile.data.value),
);
const defaultBranch = computed(() => (fromServer.value ? store.status!.git.default_branch : null) ?? "the default branch");
const legacy = computed(() => (fromServer.value ? store.status!.legacy_status : null));

const stages = computed(() => {
  const list = (store.repo?.stages ?? []).map((s) => ({ id: s.id, title: s.title }));
  for (const id of Object.keys(signoffs.value)) if (!list.some((s) => s.id === id)) list.push({ id, title: id });
  return list.map((s) => ({ ...s, signoff: signoffs.value[s.id] ?? null }));
});
const anySigned = computed(() => stages.value.some((s) => s.signoff));

function day(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
</script>

<template>
  <section v-if="stages.length" class="signoffs" aria-label="Sign-offs">
    <ol class="strip">
      <li v-for="s in stages" :key="s.id" :data-stage="s.id" :class="{ signed: s.signoff, off: s.signoff?.on_default_branch === false }">
        <span class="stage-title">{{ s.title }}</span>
        <template v-if="s.signoff">
          <span class="who">
            <span class="badge pass">signed off</span>
            {{ s.signoff.signed_by ?? "unknown signer" }}<template v-if="s.signoff.date">, {{ day(s.signoff.date) }}</template>
          </span>
          <span class="meta">
            <RouterLink v-if="s.signoff.commit && !store.snapshot" :to="{ name: 'home', query: { rev: s.signoff.commit } }" :title="`Show the plant at ${s.signoff.commit}`"><code>{{ s.signoff.commit.slice(0, 7) }}</code></RouterLink>
            <code v-else-if="s.signoff.commit">{{ s.signoff.commit.slice(0, 7) }}</code>
            <span v-if="s.signoff.branch" class="faint">on {{ s.signoff.branch }}</span>
            <RouterLink v-if="s.signoff.review" :to="{ name: 'file', params: { path: pathSegments(s.signoff.review) }, query: withRev() }" :title="s.signoff.review">review<template v-if="s.signoff.reviewer_kind && s.signoff.reviewer_kind !== 'human'"> ({{ s.signoff.reviewer_kind }})</template></RouterLink>
          </span>
          <span
            v-if="s.signoff.on_default_branch === false"
            class="badge warning"
            data-testid="not-on-default"
            :title="`The signed-off commit is not on ${defaultBranch}: the sign-off has not taken effect`"
          >not on {{ defaultBranch }}</span>
        </template>
        <span v-else class="faint">not signed off</span>
      </li>
    </ol>
    <p v-if="legacy" class="muted note">
      checks/status.json is the 0.3 kind: {{ legacy.passed }}/{{ legacy.checks }} gates passed, no stage sign-off.
    </p>
    <p v-else-if="!anySigned && !statusFile.loading.value" class="muted note">
      No stage is signed off (<code>cheme check --stage &lt;stage&gt; --write</code>).
    </p>
  </section>
</template>

<style scoped>
.strip {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(220px, 100%), 1fr));
  gap: var(--space-2);
  list-style: none;
  margin: 0;
  padding: 0;
}
.strip li {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  font-size: var(--text-sm);
  min-width: 0;
}
.strip li.signed {
  border-left: 3px solid var(--ok);
}
.strip li.off {
  border-left-color: var(--warn);
}
.stage-title {
  font-weight: 600;
  font-size: var(--text);
}
.who,
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px var(--space-2);
  align-items: center;
  overflow-wrap: anywhere;
}
.strip .badge.warning {
  align-self: flex-start;
}
.note {
  margin: var(--space-2) 0 0;
  font-size: var(--text-sm);
}
</style>
