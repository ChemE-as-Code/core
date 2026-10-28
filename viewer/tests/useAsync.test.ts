import { describe, expect, it } from "vitest";
import { effectScope, nextTick, ref } from "vue";
import { useAsync } from "@/lib/useAsync";

/** A load function whose requests the test settles by hand, keyed by the source value. */
function controlled() {
  const pending = new Map<string, { resolve: (v: string) => void; reject: (e: unknown) => void; signal: AbortSignal }>();
  const rev = ref("A");
  const load = (signal: AbortSignal) =>
    new Promise<string>((resolve, reject) => {
      pending.set(rev.value, { resolve, reject, signal });
    });
  return { pending, rev, load };
}

/** Let the awaited load and the watcher run. */
const settle = async () => {
  await Promise.resolve();
  await nextTick();
};

describe("useAsync", () => {
  it("drops the previous source's data as soon as the source changes", async () => {
    const { pending, rev, load } = controlled();
    const scope = effectScope();
    const state = scope.run(() => useAsync(load, rev))!;
    pending.get("A")!.resolve("data of A");
    await settle();
    expect(state.data.value).toBe("data of A");

    rev.value = "B";
    await nextTick();
    // B is loading: nothing of A may be shown under B's label, and the view sees `loading && !data`
    expect(state.loading.value).toBe(true);
    expect(state.data.value).toBeNull();

    pending.get("B")!.resolve("data of B");
    await settle();
    expect(state.data.value).toBe("data of B");
    expect(state.loading.value).toBe(false);
    scope.stop();
  });

  it("keeps the data on a plain reload of the same source, so a retry or refresh does not flash", async () => {
    let n = 0;
    const scope = effectScope();
    const state = scope.run(() => useAsync(async () => `run ${++n}`))!;
    await settle();
    expect(state.data.value).toBe("run 1");
    const again = state.reload();
    expect(state.loading.value).toBe(true);
    expect(state.data.value).toBe("run 1");
    await again;
    expect(state.data.value).toBe("run 2");
    scope.stop();
  });

  it("aborts the previous request when the source changes and when the scope ends", async () => {
    const { pending, rev, load } = controlled();
    const scope = effectScope();
    scope.run(() => useAsync(load, rev));
    const a = pending.get("A")!;
    rev.value = "B";
    await nextTick();
    expect(a.signal.aborted).toBe(true);
    const b = pending.get("B")!;
    expect(b.signal.aborted).toBe(false);
    scope.stop();
    expect(b.signal.aborted).toBe(true);
  });

  it("keeps only the latest request's result when responses arrive out of order", async () => {
    const { pending, rev, load } = controlled();
    const scope = effectScope();
    const state = scope.run(() => useAsync(load, rev))!;
    rev.value = "B";
    await nextTick();
    pending.get("B")!.resolve("data of B");
    await settle();
    // A answers late (a server that ignores the abort): it must not overwrite B
    pending.get("A")!.resolve("data of A");
    await settle();
    expect(state.data.value).toBe("data of B");
    expect(state.loading.value).toBe(false);

    rev.value = "C";
    await nextTick();
    pending.get("B")!.reject(new Error("late failure of B"));
    await settle();
    expect(state.error.value).toBeNull();
    expect(state.loading.value).toBe(true);
    scope.stop();
  });

  it("reports an error and no data, and ignores an abort", async () => {
    const { pending, rev, load } = controlled();
    const scope = effectScope();
    const state = scope.run(() => useAsync(load, rev))!;
    pending.get("A")!.reject(new Error("boom"));
    await settle();
    expect(state.error.value).toBe("boom");
    expect(state.data.value).toBeNull();
    expect(state.loading.value).toBe(false);

    rev.value = "B";
    await nextTick();
    expect(state.error.value).toBeNull();
    pending.get("B")!.reject(new DOMException("aborted", "AbortError"));
    await settle();
    expect(state.error.value).toBeNull();
    scope.stop();
  });

  it("does not load before it is asked to when immediate is false", async () => {
    const { pending, rev, load } = controlled();
    const scope = effectScope();
    const state = scope.run(() => useAsync(load, rev, { immediate: false }))!;
    expect(pending.size).toBe(0);
    expect(state.loading.value).toBe(false);
    rev.value = "B";
    await nextTick();
    expect([...pending.keys()]).toEqual(["B"]);
    scope.stop();
  });
});
