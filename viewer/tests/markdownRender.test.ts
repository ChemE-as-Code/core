import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, defineComponent, h, nextTick } from "vue";
import { RouterView, createRouter, createWebHashHistory } from "vue-router";
import MarkdownRender from "@/components/MarkdownRender";

const SOURCE = "See [the design basis](#design-basis).\n\n## Design basis\n\nText.\n\n## Design basis\n";

/** Mount the renderer in a hash-history router at /file/README.md, as a snapshot runs it. */
async function mount(props: Record<string, unknown> = {}) {
  window.location.hash = "#/file/README.md";
  const page = defineComponent(() => () => h(MarkdownRender, { source: SOURCE, path: "README.md", ...props }));
  const router = createRouter({
    history: createWebHashHistory(),
    routes: [
      { path: "/file/:path(.*)*", name: "file", component: page },
      { path: "/:rest(.*)*", name: "not-found", component: { render: () => h("p", "Not found") } },
    ],
  });
  const el = document.createElement("div");
  document.body.appendChild(el);
  const app = createApp({ render: () => h(RouterView) });
  app.use(router);
  await router.push("/file/README.md");
  await router.isReady();
  app.mount(el);
  await nextTick();
  return { el, router, unmount: () => (app.unmount(), el.remove()) };
}

describe("MarkdownRender", () => {
  afterEach(() => vi.restoreAllMocks());

  it("gives headings GitHub-style ids, numbered when repeated", async () => {
    const { el, unmount } = await mount();
    expect([...el.querySelectorAll("h2")].map((h2) => h2.id)).toEqual(["user-content-design-basis", "user-content-design-basis-1"]);
    unmount();
  });

  it("scrolls an in-page link to its heading without changing the route (hash history)", async () => {
    const { el, router, unmount } = await mount();
    const link = el.querySelector<HTMLAnchorElement>("a")!;
    // The current route with the fragment: opened in a new tab, it is still this page.
    expect(link.getAttribute("href")).toBe("#/file/README.md#design-basis");
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled;
    link.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 }));
    await nextTick();
    expect(scrolled).toHaveBeenCalledTimes(1);
    expect(document.activeElement?.id).toBe("user-content-design-basis");
    expect(router.currentRoute.value.name).toBe("file");
    expect(window.location.hash).toBe("#/file/README.md");
    unmount();
  });

  it("never gives a heading one of the app's own ids", async () => {
    const { el, unmount } = await mount({ source: "# Main\n\n[top](#main)\n" });
    expect(el.querySelector("h1")?.id).toBe("user-content-main");
    unmount();
  });

  it("leaves headings without ids where several documents share a page", async () => {
    const { el, unmount } = await mount({ headingIds: false });
    expect([...el.querySelectorAll("h2")].every((h2) => !h2.id)).toBe(true);
    unmount();
  });
});
