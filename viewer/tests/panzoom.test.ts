import { describe, expect, it } from "vitest";
import { createView, fitView, zoomAt, MAX_SCALE } from "@/lib/panzoom";

describe("panzoom", () => {
  it("keeps the zoom point fixed", () => {
    const view = createView();
    zoomAt(view, 2, 100, 50);
    expect(view).toMatchObject({ k: 2, x: -100, y: -50 });
    // The drawing point under (100, 50) is still (100, 50).
    expect((100 - view.x) / view.k).toBe(100);
  });
  it("clamps the scale", () => {
    const view = createView();
    zoomAt(view, 1e6, 0, 0);
    expect(view.k).toBe(MAX_SCALE);
  });
  it("fits and centres", () => {
    const view = createView();
    fitView(view, 1000, 600, 420, 297, 0);
    expect(view.k).toBeCloseTo(600 / 297);
    expect(view.y).toBeCloseTo(0);
    expect(view.x).toBeCloseTo((1000 - 420 * view.k) / 2);
  });
});
