import { afterEach, describe, expect, it } from "vitest";
import { effectScope, nextTick, ref, shallowRef } from "vue";
import { refocusAfterLoad } from "@/lib/refocus";

/** A case select that the page removes while it loads and draws again with the data. */
function page() {
  const data = shallowRef<string | null>("design");
  const loading = ref(false);
  const rev = ref("A");
  const draw = () => {
    document.body.replaceChildren();
    const select = document.createElement("select");
    select.setAttribute("aria-label", "Case");
    document.body.appendChild(select);
    return select;
  };
  draw().focus();
  const scope = effectScope();
  const keep = scope.run(() => refocusAfterLoad('select[aria-label="Case"]', { data, loading }, rev))!;
  /** Pick another case: arm, drop the select, load, end the load with `result`. */
  const pick = async (result: string | null, between?: () => void) => {
    keep();
    document.body.replaceChildren();
    data.value = null;
    loading.value = true;
    await nextTick();
    between?.();
    await nextTick();
    data.value = result;
    if (result) draw();
    loading.value = false;
    await nextTick();
    await nextTick();
  };
  return { pick, rev, scope };
}

describe("refocusAfterLoad", () => {
  afterEach(() => document.body.replaceChildren());

  it("gives the redrawn select the focus once the case has loaded", async () => {
    const { pick, scope } = page();
    await pick("turndown");
    expect((document.activeElement as HTMLElement).getAttribute("aria-label")).toBe("Case");
    scope.stop();
  });

  it("does nothing when the load fails or finds nothing", async () => {
    const { pick, scope } = page();
    await pick(null);
    expect(document.activeElement).toBe(document.body);
    scope.stop();
  });

  it("does nothing when another revision is asked for first", async () => {
    const { pick, rev, scope } = page();
    await pick("design", () => (rev.value = "B"));
    expect(document.activeElement).toBe(document.body);
    scope.stop();
  });
});
