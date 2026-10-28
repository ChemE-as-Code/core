import { ref, shallowRef, watch, onScopeDispose, type Ref, type ShallowRef, type WatchSource } from "vue";

export interface AsyncState<T> {
  data: ShallowRef<T | null>;
  error: Ref<string | null>;
  loading: Ref<boolean>;
  reload: () => Promise<void>;
}

/**
 * Run `load` now and whenever `source` changes, cancelling the previous request. Only the
 * latest request's result is kept.
 *
 * A change of `source` (another revision, case, file, ...) clears `data` at once: the previous
 * source's result must never be shown under the new one's label while it loads, so views see
 * `loading && !data` and show their loading state. A plain `reload()` (retry, refresh) of the
 * same source keeps the data until the new result arrives, so it does not flash.
 */
export function useAsync<T>(
  load: (signal: AbortSignal) => Promise<T>,
  source?: WatchSource | WatchSource[],
  options: { immediate?: boolean } = {},
): AsyncState<T> {
  const data = shallowRef<T | null>(null);
  const error = ref<string | null>(null);
  const loading = ref(false);
  let controller: AbortController | null = null;

  async function reload(): Promise<void> {
    controller?.abort();
    const current = new AbortController();
    controller = current;
    loading.value = true;
    error.value = null;
    try {
      const result = await load(current.signal);
      if (controller === current) data.value = result;
    } catch (e) {
      if (controller !== current || (e instanceof DOMException && e.name === "AbortError")) return;
      data.value = null;
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      if (controller === current) loading.value = false;
    }
  }

  function changed(): void {
    data.value = null;
    void reload();
  }

  if (source) watch(source, changed, { immediate: options.immediate ?? true });
  else if (options.immediate ?? true) void reload();
  onScopeDispose(() => controller?.abort());
  return { data, error, loading, reload };
}
