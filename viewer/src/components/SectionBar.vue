<script setup lang="ts">
/**
 * A bar of links to the sections of a long page (#67). It reads the page it
 * sits in: every `<section>` beside it with an `<h2>` is a section, named by its `aria-label` or
 * its heading's first words, and gets an id when it has none (`sec-<name>`), so `#sec-loops`
 * deep-links. It stays at the top while the page scrolls, marks the section in view, and uses
 * the in-page links (src/lib/inPageLink.ts), so it works in a snapshot's hash URLs too. With
 * fewer than `min` sections (three) it shows nothing.
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { fragmentOf, scrollToId, useInPageLink } from "@/lib/inPageLink";
import { sectionId, sectionLabel } from "@/lib/sections";

interface Item {
  id: string;
  label: string;
}

/** Fewer sections than this: no bar (a short page needs none). */
const props = withDefaults(defineProps<{ min?: number }>(), { min: 3 });
const bar = ref<HTMLElement | null>(null);
const items = ref<Item[]>([]);
const current = ref<string | null>(null);
const route = useRoute();
const inPage = useInPageLink();
let observer: MutationObserver | null = null;
let scroller: HTMLElement | null = null;
let frame = 0;
let scrolledToHash = false;

function scan(): void {
  const page = bar.value?.parentElement;
  if (!page) return;
  const used = new Set<string>();
  const next: Item[] = [];
  for (const section of page.querySelectorAll<HTMLElement>(":scope > section")) {
    const heading = section.querySelector<HTMLElement>("h2");
    if (!heading) continue;
    const label = sectionLabel(section.getAttribute("aria-label"), heading.textContent ?? "");
    if (!label) continue;
    if (!section.id) section.id = sectionId(label, used);
    used.add(section.id);
    next.push({ id: section.id, label });
  }
  if (next.map((i) => i.id).join() !== items.value.map((i) => i.id).join() || next.some((i, k) => i.label !== items.value[k]?.label))
    items.value = next;
  // A link to a section (`/control#sec-loops`), once the section is there.
  const id = fragmentOf(route.hash);
  if (!scrolledToHash && id && next.some((i) => i.id === id)) {
    scrolledToHash = true;
    void nextTick(() => scrollToId(id));
  }
  spy();
}

/** The section in view: the last one whose top has passed the bar, or the last one at the bottom. */
function spy(): void {
  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(() => {
    if (scroller && scroller.scrollTop > 0 && scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 2) {
      current.value = items.value[items.value.length - 1]?.id ?? null;
      return;
    }
    const line = (bar.value?.getBoundingClientRect().bottom ?? 0) + 8;
    let id: string | null = null;
    for (const item of items.value) {
      const top = document.getElementById(item.id)?.getBoundingClientRect().top;
      if (top !== undefined && top <= line) id = item.id;
    }
    current.value = id ?? items.value[0]?.id ?? null;
  });
}

function open(event: MouseEvent, id: string): void {
  inPage.go(event, id);
  if (event.defaultPrevented) current.value = id;
}

onMounted(() => {
  const page = bar.value?.parentElement;
  if (!page) return;
  scan();
  observer = new MutationObserver(scan);
  observer.observe(page, { childList: true, subtree: true, attributes: true, attributeFilter: ["aria-label"] });
  scroller = page.closest<HTMLElement>("main") ?? null;
  scroller?.addEventListener("scroll", spy, { passive: true });
});
onBeforeUnmount(() => {
  observer?.disconnect();
  scroller?.removeEventListener("scroll", spy);
  cancelAnimationFrame(frame);
});
watch(() => route.hash, () => (scrolledToHash = false));
</script>

<template>
  <nav ref="bar" class="section-bar" :class="{ empty: items.length < props.min }" aria-label="Sections" data-testid="section-bar">
    <template v-if="items.length >= props.min">
      <a
        v-for="item in items"
        :key="item.id"
        :href="inPage.href(item.id)"
        :class="{ current: item.id === current }"
        :aria-current="item.id === current ? 'location' : undefined"
        @click="open($event, item.id)"
        >{{ item.label }}</a
      >
    </template>
  </nav>
</template>

<style scoped>
.section-bar {
  position: sticky;
  top: 0;
  z-index: 15;
  display: flex;
  gap: var(--space-1);
  margin: 0 calc(-1 * var(--space-2)) var(--space-3);
  padding: var(--space-1) var(--space-2);
  overflow-x: auto;
  scrollbar-width: thin;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  font-size: var(--text-sm);
}
.section-bar.empty {
  display: none;
}
.section-bar a {
  flex: none;
  padding: 2px var(--space-2);
  border-radius: 999px;
  color: var(--fg-muted);
  white-space: nowrap;
}
.section-bar a:hover {
  color: var(--fg);
  background: var(--bg-sunk);
  text-decoration: none;
}
.section-bar a.current {
  color: var(--fg);
  background: var(--accent-soft);
}
</style>
