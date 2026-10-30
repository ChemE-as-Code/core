<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, type Commit } from "@/api";
import LoadState from "@/components/LoadState.vue";
import { useAsync } from "@/lib/useAsync";
import { useRev } from "@/lib/useRev";
import { formatDate, kindFromPath, pathSegments, shortRev, viewFor } from "@/lib/format";
import { store } from "@/store";

const route = useRoute();
const router = useRouter();
const { rev } = useRev();
const path = computed(() => {
  const value = route.query.path;
  const first = Array.isArray(value) ? value[0] : value;
  return first ? String(first) : "";
});
const limit = ref(50);
const log = useAsync((signal) => api.log({ limit: limit.value, path: path.value || undefined, rev: rev.value }, signal), [path, rev]);
// "Load more" asks for a longer log of the same file and revision: the list stays while it loads.
watch(limit, () => void log.reload());

const isSheet = computed(() => !!path.value && kindFromPath(path.value) === "pid");
/** Selected shas, at most two, in the order they were picked. */
const selected = ref<string[]>([]);
watch([path, rev], () => (selected.value = []));

function toggle(commit: Commit): void {
  const list = selected.value.filter((sha) => sha !== commit.sha);
  if (list.length === selected.value.length) list.push(commit.sha);
  selected.value = list.slice(-2);
}

/** The two selected commits as old/new by their position in the log (older is further down). */
const pair = computed(() => {
  const commits = log.data.value ?? [];
  const index = (sha: string) => commits.findIndex((c) => c.sha === sha);
  const sorted = [...selected.value].sort((a, b) => index(b) - index(a));
  return { old: sorted[0], new: sorted[1] };
});

function compare(): void {
  if (!isSheet.value || !pair.value.old) return;
  const query: Record<string, string> = { old: pair.value.old };
  if (pair.value.new) query.new = pair.value.new;
  void router.push({ name: "diff", params: { path: pathSegments(path.value) }, query });
}

function setPath(value: string): void {
  const query = { ...route.query };
  if (value) query.path = value;
  else delete query.path;
  void router.replace({ query });
}

const sheetOptions = computed(() => store.repo?.sheets ?? []);
const fileLink = (sha: string) =>
  path.value ? { name: viewFor(kindFromPath(path.value)), params: { path: pathSegments(path.value) }, query: { rev: sha } } : null;
</script>

<template>
  <div class="page">
    <h1>History <small>{{ path || "the whole plant" }} &middot; {{ shortRev(rev) === "working tree" ? "HEAD" : shortRev(rev) }}</small></h1>
    <div class="toolbar">
      <label>
        <span class="sr-only">File</span>
        <select :value="path" @change="setPath(($event.target as HTMLSelectElement).value)">
          <option value="">All files</option>
          <option v-for="s in sheetOptions" :key="s.file" :value="s.file">{{ s.id }} &mdash; {{ s.file }}</option>
          <option v-if="path && !sheetOptions.some((s) => s.file === path)" :value="path">{{ path }}</option>
        </select>
      </label>
      <span class="spacer" />
      <template v-if="isSheet">
        <span class="muted hint">
          {{ selected.length === 0 ? "Select one or two commits" : selected.length === 1 ? "One selected: compares with the working tree" : "Two selected" }}
        </span>
        <button class="btn primary" type="button" :disabled="!selected.length" @click="compare">Open diff</button>
      </template>
      <span v-else-if="path" class="muted hint">Diffs are available for P&amp;ID sheets.</span>
    </div>

    <LoadState :loading="log.loading.value && !log.data.value" :error="log.error.value" @retry="log.reload" />
    <template v-if="log.data.value">
      <p v-if="!log.data.value.length" class="notice">No commits.</p>
      <div v-else class="table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th v-if="isSheet"><span class="sr-only">Select</span></th>
              <th>commit</th>
              <th>subject</th>
              <th>author</th>
              <th>date</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in log.data.value" :key="c.sha" :class="{ selected: selected.includes(c.sha), clickable: isSheet }" @click="isSheet && toggle(c)">
              <td v-if="isSheet" @click.stop>
                <input type="checkbox" :checked="selected.includes(c.sha)" :aria-label="`Select ${c.short}`" @change="toggle(c)" />
                <span v-if="pair.old === c.sha" class="badge removed tag">old</span>
                <span v-else-if="pair.new === c.sha" class="badge added tag">new</span>
              </td>
              <td>
                <RouterLink v-if="fileLink(c.sha)" :to="fileLink(c.sha)!" :title="`Show ${path} at ${c.short}`" @click.stop><code>{{ c.short }}</code></RouterLink>
                <code v-else :title="c.sha">{{ c.short }}</code>
              </td>
              <td class="subject">{{ c.subject }}</td>
              <td class="nowrap">{{ c.author }}</td>
              <td class="nowrap" :title="c.date">{{ formatDate(c.date) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="log.data.value.length >= limit" class="more">
        <button class="btn" type="button" @click="limit += 50">Load more</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.hint {
  font-size: var(--text-sm);
}
.nowrap {
  white-space: nowrap;
}
.subject {
  min-width: 220px;
}
.tag {
  margin-left: 4px;
}
.more {
  margin-top: var(--space-3);
}
</style>
