<script setup lang="ts">
import { computed, nextTick, ref, watch, watchEffect, onMounted } from "vue";
import { START_LOCATION, useRoute, useRouter } from "vue-router";
import AppHeader from "@/components/AppHeader.vue";
import SideNav from "@/components/SideNav.vue";
import { loadRepo, store } from "@/store";
import { fullViewerHref } from "@/lib/viewerOptions";
import { pageTitle } from "@/router";
import { useInPageLink } from "@/lib/inPageLink";

const route = useRoute();
const sidebarOpen = ref(false);
const main = ref<HTMLElement | null>(null);
const inPage = useInPageLink();

onMounted(() => void loadRepo());
// On phones the sidebar is a drawer: close it after navigating.
watch(
  () => route.fullPath,
  () => (sidebarOpen.value = false),
);
// The tab title and the history say which page this is.
watchEffect(() => (document.title = pageTitle(route, store.repo?.name || store.repo?.root_name)));
// After navigating to another page (not on the first load, not for a new ?rev= or #fragment),
// the focus moves to the new page's heading, so a keyboard or screen-reader user starts there.
useRouter().afterEach(async (to, from, failure) => {
  if (failure || from === START_LOCATION || to.path === from.path) return;
  await nextTick();
  const target = main.value?.querySelector<HTMLElement>("h1") ?? main.value;
  if (!target) return;
  if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
  target.focus({ preventScroll: true });
});
// Embedded: the current page without `embed`. The router has updated the URL by the time
// route.fullPath changes, so reading it makes the link follow the route.
const fullViewer = computed(() => {
  void route.fullPath;
  return fullViewerHref(window.location.href);
});
</script>

<template>
  <div class="shell" :class="{ 'sidebar-open': sidebarOpen, embed: store.embed }">
    <a class="skip-link" :href="inPage.href('main')" @click="inPage.go($event, 'main')">Skip to content</a>
    <template v-if="!store.embed">
      <AppHeader class="shell-header" :sidebar-open="sidebarOpen" @toggle-sidebar="sidebarOpen = !sidebarOpen" />
      <aside class="shell-sidebar" aria-label="Navigation">
        <SideNav />
      </aside>
      <div v-if="sidebarOpen" class="scrim" @click="sidebarOpen = false" />
    </template>
    <main id="main" ref="main" class="shell-main" tabindex="-1">
      <div v-if="store.error" class="notice error page-notice" role="alert">
        <strong>Cannot load the repository.</strong> {{ store.error }}
        <button class="btn" type="button" @click="loadRepo">Retry</button>
      </div>
      <RouterView :key="route.path" />
    </main>
    <a
      v-if="store.embed"
      class="full-viewer"
      :href="fullViewer"
      target="_blank"
      rel="noopener"
      data-testid="open-full-viewer"
      >Open full viewer &#8599;</a
    >
  </div>
</template>

<style scoped>
.shell {
  display: grid;
  grid-template-columns: var(--sidebar-w) minmax(0, 1fr);
  grid-template-rows: var(--header-h) minmax(0, 1fr);
  grid-template-areas:
    "header header"
    "sidebar main";
  height: 100%;
}
.shell-header {
  grid-area: header;
}
.shell-sidebar {
  grid-area: sidebar;
  overflow: auto;
  border-right: 1px solid var(--border);
  background: var(--bg-soft);
}
.shell-main {
  grid-area: main;
  overflow: auto;
  min-width: 0;
  position: relative;
}
/* Embedded (?embed=1): the routed view fills the frame. The "Open full viewer" link sits bottom
   left, clear of the P&ID zoom buttons and the 3D legend at the bottom right. */
.shell.embed {
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);
  grid-template-areas: "main";
}
.full-viewer {
  position: fixed;
  left: var(--space-2);
  bottom: var(--space-2);
  z-index: 40;
  padding: 2px var(--space-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--fg-muted);
  font-size: var(--text-sm);
}
.full-viewer:hover,
.full-viewer:focus-visible {
  color: var(--fg);
  text-decoration: none;
}
.skip-link {
  position: absolute;
  left: var(--space-2);
  top: -100px;
  z-index: 50;
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
}
.skip-link:focus {
  top: var(--space-2);
}
.shell-main:focus,
.shell-main :deep(h1[tabindex="-1"]:focus) {
  outline: none;
}
.page-notice {
  margin: var(--space-3) var(--space-4);
}
.scrim {
  display: none;
}

@media (max-width: 860px) {
  .shell {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      "header"
      "main";
  }
  .shell-sidebar {
    position: fixed;
    top: var(--header-h);
    bottom: 0;
    left: 0;
    width: min(320px, 86vw);
    z-index: 30;
    transform: translateX(-100%);
    transition: transform 0.18s ease;
    box-shadow: var(--shadow);
  }
  .sidebar-open .shell-sidebar {
    transform: none;
  }
  .scrim {
    display: block;
    position: fixed;
    inset: var(--header-h) 0 0 0;
    background: rgba(0, 0, 0, 0.3);
    z-index: 20;
  }
}
</style>
