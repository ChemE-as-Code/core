import { createApp } from "vue";
import App from "./App.vue";
import PlantsApp from "./PlantsApp.vue";
import { getPlants, usePlant, useSnapshot } from "./api";
import { loadSnapshot } from "./dataSource";
import { plantFromPath, safeBackUrl } from "./lib/plants";
import { applyTheme, viewerOptions } from "./lib/viewerOptions";
import { createAppRouter } from "./router";
import { store } from "./store";
import "./styles.css";

// `?data=<snapshot directory>` opens a static snapshot (cheme export-static) instead of talking to
// a server; routes then live in the hash, so the page itself can be served from any static host.
// `?embed=1` and `?theme=` (src/lib/viewerOptions.ts) sit next to it and are read once here too.
async function start(): Promise<void> {
  const data = new URLSearchParams(window.location.search).get("data");
  const options = viewerOptions(window.location.search);
  applyTheme(options.theme);
  store.embed = options.embed;
  const back = safeBackUrl(options.back, window.location.href);
  store.back = back ? { href: back, label: options.backLabel || "Back" } : null;
  // A plant of a library server (`/p/<id>/`, core's ADR 0034): its API and its routes under it.
  const plant = data ? null : plantFromPath(window.location.pathname);
  if (plant) {
    usePlant(plant.id);
    store.plant = plant.id;
    void getPlants().then(
      (index) => (store.plants = index),
      () => {},
    );
  } else if (!data) {
    // The root of a library server: its index of the plants. A 404 means one plant, as before.
    try {
      const index = await getPlants();
      createApp(PlantsApp, { index }).mount("#app");
      return;
    } catch {
      // a server of one plant (or none reachable: the plant view says so)
    }
  }
  if (data) {
    try {
      const source = await loadSnapshot(data);
      useSnapshot(source);
      store.snapshot = { commit: source.manifest.source.commit, tool: source.manifest.source.tool, dirty: source.manifest.source.dirty };
    } catch (error) {
      store.snapshotError = error instanceof Error ? error.message : String(error);
    }
  }
  createApp(App).use(createAppRouter(data ? "hash" : "web", plant?.base)).mount("#app");
}

void start();
