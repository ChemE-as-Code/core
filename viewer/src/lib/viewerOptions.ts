// Page options in the query string before the hash, read once at startup (like `?data=`), so
// they stay when the hash route changes. The Process Atlas relies on exactly these:
//   ?embed=1                  no header, no file tree; the routed view fills the frame
//   ?theme=light|dark|system  force the colour scheme (default: system)
//   ?back=<url>&back_label=   a link back to the page that opened it (this site only)

export type ThemeChoice = "light" | "dark" | "system";

export interface ViewerOptions {
  embed: boolean;
  theme: ThemeChoice;
  /** `?back=`, as given (src/lib/plants.ts `safeBackUrl` decides whether it is linked). */
  back: string | null;
  backLabel: string | null;
}

/** Parse `location.search`. Unknown values fall back to the defaults (not embedded, system theme). */
export function viewerOptions(search: string): ViewerOptions {
  const params = new URLSearchParams(search);
  const embed = params.get("embed");
  const theme = params.get("theme");
  return {
    embed: embed === "1" || embed === "true",
    theme: theme === "light" || theme === "dark" ? theme : "system",
    back: params.get("back"),
    backLabel: params.get("back_label"),
  };
}

/**
 * Set `data-theme` on `<html>` for a forced theme (styles.css and the 3D view read it); the
 * system theme leaves it unset so `prefers-color-scheme` decides.
 */
export function applyTheme(theme: ThemeChoice, root: HTMLElement = document.documentElement): void {
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
}

/** Whether the page shows the dark scheme: the forced theme, else the system preference. */
export function isDarkScheme(root: HTMLElement = document.documentElement): boolean {
  const forced = root.dataset.theme;
  if (forced === "dark" || forced === "light") return forced === "dark";
  return Boolean(window.matchMedia?.("(prefers-color-scheme: dark)").matches);
}

/** The same page without `embed`: the full viewer, for the "Open full viewer" link. */
export function fullViewerHref(href: string): string {
  const url = new URL(href);
  url.searchParams.delete("embed");
  return url.toString();
}
