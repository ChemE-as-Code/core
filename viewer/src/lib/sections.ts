/** Names and ids of a page's sections for the section bar (src/components/SectionBar.vue). */

/** A section's name: its `aria-label`, else its heading's text up to the first number or note. */
export function sectionLabel(ariaLabel: string | null, heading: string): string {
  const label = ariaLabel?.trim();
  if (label) return label;
  // "Loops 33 reviewed", "Requirements (14)": the words before the count
  const words = heading.trim().replace(/\s+/g, " ").split(/\s(?=[\d(])/)[0] ?? "";
  return words.length > 40 ? `${words.slice(0, 39)}…` : words;
}

/** `sec-<slug>`, made unique among `used`. */
export function sectionId(label: string, used: ReadonlySet<string>): string {
  const slug =
    label
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "") || "section";
  let id = `sec-${slug}`;
  for (let n = 2; used.has(id); n++) id = `sec-${slug}-${n}`;
  return id;
}
