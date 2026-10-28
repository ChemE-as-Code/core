/** Resolve `href` (relative to the file at `from`) to a repo-relative path; null if it leaves the repo. */
export function resolveRepoPath(from: string, href: string): string | null {
  const clean = href.split("#")[0]?.split("?")[0] ?? "";
  if (!clean) return null;
  const base = clean.startsWith("/") ? [] : from.split("/").slice(0, -1);
  const parts = [...base];
  for (const segment of clean.split("/")) {
    if (!segment || segment === ".") continue;
    if (segment === "..") {
      if (!parts.length) return null;
      parts.pop();
    } else parts.push(decodeURIComponentSafe(segment));
  }
  return parts.length ? parts.join("/") : null;
}

function decodeURIComponentSafe(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}
