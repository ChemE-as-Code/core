import { computed } from "vue";
import { useRoute, type LocationQueryRaw } from "vue-router";

/** The revision shown, from the `rev` query parameter; undefined means the working tree. */
export function useRev() {
  const route = useRoute();
  const rev = computed<string | undefined>(() => {
    const value = route.query.rev;
    const first = Array.isArray(value) ? value[0] : value;
    return first ? String(first) : undefined;
  });
  /** `query` plus the current rev, for links that keep the revision. */
  const withRev = (query: LocationQueryRaw = {}): LocationQueryRaw =>
    rev.value ? { ...query, rev: rev.value } : { ...query };
  return { rev, withRev };
}
