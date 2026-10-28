import { useRoute, useRouter } from "vue-router";

/**
 * Scroll to the element with DOM id `id` and give it the focus (a keyboard or screen-reader user
 * continues from there). False when there is no such element.
 */
export function scrollToId(id: string): boolean {
  const target = document.getElementById(id);
  if (!target) return false;
  target.scrollIntoView?.({ block: "start" });
  if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
  target.focus({ preventScroll: true });
  return true;
}

/** `#design-basis` -> `design-basis` (percent-decoded); null for anything but a fragment. */
export function fragmentOf(href: string): string | null {
  if (!href.startsWith("#") || href.length < 2) return null;
  try {
    return decodeURIComponent(href.slice(1));
  } catch {
    return href.slice(1);
  }
}

/**
 * Links to a place in the current page. A plain `<a href="#id">` replaces the route in a
 * snapshot (hash history: the URL's hash is the route) and lands on Not found. `href(id)` is the
 * current route with that hash, in either router mode, so opening the link in a new tab or
 * copying it works; `go` scrolls there without navigating.
 */
export function useInPageLink() {
  const route = useRoute();
  const router = useRouter();
  const href = (id: string) => router.resolve({ path: route.path, query: route.query, hash: `#${id}` }).href;
  function go(event: MouseEvent, id: string): void {
    // A new tab or window (middle click, Ctrl/Cmd/Shift click) follows `href`.
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    scrollToId(id);
  }
  return { href, go };
}
