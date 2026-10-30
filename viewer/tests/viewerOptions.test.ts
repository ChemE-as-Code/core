/// <reference types="node" />
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { applyTheme, fullViewerHref, isDarkScheme, viewerOptions } from "@/lib/viewerOptions";

describe("viewerOptions", () => {
  it("defaults to the full app in the system theme", () => {
    expect(viewerOptions("")).toEqual({ embed: false, theme: "system", back: null, backLabel: null });
    expect(viewerOptions("?data=../snapshot/")).toEqual({ embed: false, theme: "system", back: null, backLabel: null });
  });

  it("reads embed and theme next to data", () => {
    expect(viewerOptions("?data=../snapshot/&embed=1&theme=dark")).toEqual({ embed: true, theme: "dark", back: null, backLabel: null });
    expect(viewerOptions("?embed=true&theme=light")).toEqual({ embed: true, theme: "light", back: null, backLabel: null });
    expect(viewerOptions("?theme=system")).toEqual({ embed: false, theme: "system", back: null, backLabel: null });
  });

  it("ignores unknown values", () => {
    expect(viewerOptions("?embed=0&theme=sepia")).toEqual({ embed: false, theme: "system", back: null, backLabel: null });
    expect(viewerOptions("?embed=&theme=")).toEqual({ embed: false, theme: "system", back: null, backLabel: null });
  });

  it("reads the page to link back to (src/lib/plants.ts decides whether it is linked)", () => {
    expect(viewerOptions("?data=x/&back=/processes/asu-1/&back_label=Process%20Atlas")).toMatchObject({ back: "/processes/asu-1/", backLabel: "Process Atlas" });
  });
});

describe("applyTheme", () => {
  it("sets data-theme for a forced theme and removes it for system", () => {
    const root = document.createElement("html");
    applyTheme("dark", root);
    expect(root.dataset.theme).toBe("dark");
    expect(isDarkScheme(root)).toBe(true);
    applyTheme("light", root);
    expect(root.dataset.theme).toBe("light");
    expect(isDarkScheme(root)).toBe(false);
    applyTheme("system", root);
    expect(root.hasAttribute("data-theme")).toBe(false);
  });
});

describe("fullViewerHref", () => {
  it("drops embed and keeps data, theme and the hash route", () => {
    expect(fullViewerHref("https://atlas.example/viewer/?data=..%2Fsnapshot%2F&embed=1&theme=dark#/pid/process/PFD.xml")).toBe(
      "https://atlas.example/viewer/?data=..%2Fsnapshot%2F&theme=dark#/pid/process/PFD.xml",
    );
    expect(fullViewerHref("http://localhost:5173/layout?embed=1")).toBe("http://localhost:5173/layout");
  });
});

describe("styles.css", () => {
  // The dark tokens are written twice (system preference, forced ?theme=dark); they must match.
  it("has the same dark tokens for the system preference and the forced theme", () => {
    // Read from disk: a CSS import is empty under vitest. Tests run from the package root.
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf-8");
    const block = (start: string): string => {
      const from = css.indexOf(start);
      expect(from).toBeGreaterThan(-1);
      return css.slice(from + start.length, css.indexOf("}", from));
    };
    const tokens = (text: string): string[] =>
      text
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .split(";")
        .map((d) => d.trim())
        .filter((d) => d.startsWith("--"));
    const system = tokens(block(':root:not([data-theme="light"]) {'));
    const forced = tokens(block(':root[data-theme="dark"] {'));
    expect(system.length).toBeGreaterThan(20);
    expect(forced).toEqual(system);
    expect(system).toContain("--paper: #f4f4f2");
  });
});
