import { nextTick, watch, type Ref, type WatchSource } from "vue";

/**
 * A control drawn from loaded data (a case select) disappears while its page loads the choice:
 * `useAsync` clears the previous data. Call the returned function when the control changes the
 * choice; when that load ends with data, the control matching `selector` gets the focus back, so
 * a keyboard user is not dropped to the top of the page. Nothing happens when the control did not
 * have the focus, when the load fails or finds nothing, or when `cancel` changes first (another
 * revision: the load that ends is no longer the one the control asked for).
 */
export function refocusAfterLoad(
  selector: string,
  state: { data: Ref<unknown>; loading: Ref<boolean> },
  cancel?: WatchSource,
): () => void {
  let pending = false;
  watch(state.loading, async (loading) => {
    if (loading || !pending) return;
    pending = false;
    if (state.data.value == null) return;
    await nextTick();
    document.querySelector<HTMLElement>(selector)?.focus();
  });
  if (cancel) watch(cancel, () => (pending = false));
  return () => {
    pending = document.activeElement instanceof Element && document.activeElement.matches(selector);
  };
}
