import { afterEach, describe, expect, it, vi } from "vitest";
import { signalEmbed, signalEmbedSelection } from "@/lib/embedSignal";
import { store } from "@/store";

const parentOf = (postMessage: (...args: unknown[]) => void) => vi.spyOn(window, "parent", "get").mockReturnValue({ postMessage } as unknown as Window & typeof globalThis);

describe("signalEmbed", () => {
  afterEach(() => {
    store.embed = false;
    window.location.hash = "";
    vi.restoreAllMocks();
  });

  it("reports the stage and route to the parent, on this origin only", () => {
    const post = vi.fn();
    parentOf(post);
    store.embed = true;
    window.location.hash = "#/pid/process/PFD.xml?select=P-1";
    signalEmbed("visual");
    expect(post).toHaveBeenCalledWith({ type: "cheme-viewer", version: 1, stage: "visual", route: "/pid/process/PFD.xml" }, window.location.origin);
  });

  it("reports the picked object, and that it is gone", () => {
    const post = vi.fn();
    parentOf(post);
    store.embed = true;
    window.location.hash = "#/layout";
    signalEmbedSelection("K-1101");
    signalEmbedSelection(null);
    expect(post).toHaveBeenNthCalledWith(1, { type: "cheme-viewer", version: 1, route: "/layout", stage: "select", select: "K-1101" }, window.location.origin);
    expect(post).toHaveBeenNthCalledWith(2, { type: "cheme-viewer", version: 1, route: "/layout", stage: "select", select: null }, window.location.origin);
  });

  it("says nothing when not embedded", () => {
    const post = vi.fn();
    parentOf(post);
    signalEmbed("visual");
    expect(post).not.toHaveBeenCalled();
  });

  it("says nothing without a parent", () => {
    store.embed = true;
    const post = vi.spyOn(window, "postMessage");
    signalEmbed("visual");
    expect(post).not.toHaveBeenCalled();
  });
});
