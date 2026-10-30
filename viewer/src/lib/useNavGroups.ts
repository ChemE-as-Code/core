import { computed } from "vue";
import { store } from "@/store";
import { hasReviewData } from "@/lib/reviews";
import { navGroups } from "@/lib/pages";

/** The navigation groups of the plant loaded (src/lib/pages.ts): the sidebar and the overview. */
export function useNavGroups() {
  return computed(() =>
    navGroups({
      repo: store.repo,
      // the sheets drawn in the working tree (a planned sheet has nothing to open yet)
      sheets: (store.repo?.sheets ?? []).filter((s) => s.status !== "planned" && (!store.paths || store.paths.has(s.file))),
      paths: store.paths,
      hasDatasheets: store.hasDatasheets,
      hasInterlocks: store.hasInterlocks,
      hasReviews: hasReviewData(store.status),
      snapshot: Boolean(store.snapshot),
    }),
  );
}
