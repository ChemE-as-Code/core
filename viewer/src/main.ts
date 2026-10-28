import { createApp } from "vue";
import App from "./App.vue";
import { useSnapshot } from "./api";
import { loadSnapshot } from "./dataSource";
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
  if (data) {
    try {
      const source = await loadSnapshot(data);
      useSnapshot(source);
      store.snapshot = { commit: source.manifest.source.commit, tool: source.manifest.source.tool, dirty: source.manifest.source.dirty };
    } catch (error) {
      store.snapshotError = error instanceof Error ? error.message : String(error);
    }
  }
  createApp(App).use(createAppRouter(data ? "hash" : "web")).mount("#app");
}

void start();
