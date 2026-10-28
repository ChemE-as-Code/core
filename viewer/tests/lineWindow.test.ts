import { describe, expect, it } from "vitest";
import { lineWindow, MAX_ROWS, WINDOW_RADIUS } from "@/lib/lineWindow";

describe("lineWindow", () => {
  it("shows every row of a short file", () => {
    expect(lineWindow(10, null)).toEqual({ first: 1, last: 10, partial: false });
    expect(lineWindow(MAX_ROWS, 5)).toEqual({ first: 1, last: MAX_ROWS, partial: false });
  });

  it("shows a long file without a target as plain text", () => {
    expect(lineWindow(32095, null)).toBeNull();
  });

  it("keeps a numbered row for the target line of a long file", () => {
    const w = lineWindow(32095, 12000);
    expect(w).toEqual({ first: 12000 - WINDOW_RADIUS, last: 12000 + WINDOW_RADIUS, partial: true });
    expect(w!.first <= 12000 && 12000 <= w!.last).toBe(true);
    expect(lineWindow(32095, 3)).toEqual({ first: 1, last: 3 + WINDOW_RADIUS, partial: true });
    expect(lineWindow(32095, 99999)).toEqual({ first: 32095 - WINDOW_RADIUS, last: 32095, partial: true });
  });
});
