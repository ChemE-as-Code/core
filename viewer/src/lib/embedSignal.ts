// What the embedding page (the Process Atlas) may wait for: a small, versioned postMessage protocol,
// to the same origin only and only when embedded (?embed=1). `route` is the hash route the stage
// belongs to, so that a page can ignore a stage of the view it has already left.
//   app     the Viewer runs and has routed; pages without a signal of their own show their own loading state
//   visual  the first useful picture: a drawing, or the 3D overview
//   detail  the 3D model's fine geometry is complete
//   error   the view could not load
//   select  the object picked in this view (`select`, null when none), for the next view to keep
import { store } from "@/store";

export type EmbedStage = "app" | "visual" | "detail" | "error";

function post(message: Record<string, unknown>): void {
  if (!store.embed || window.parent === window) return;
  const route = window.location.hash.replace(/^#/, "").split("?")[0] ?? "";
  window.parent.postMessage({ type: "cheme-viewer", version: 1, route, ...message }, window.location.origin);
}

export function signalEmbed(stage: EmbedStage): void {
  post({ stage });
}

export function signalEmbedSelection(select: string | null): void {
  post({ stage: "select", select });
}
