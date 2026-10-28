/**
 * Find a drawn object of a P&ID by its printed tag. The SVG's `g.representation-group`s carry
 * DEXPI ids (`P4101A`, `Inst_LIA4107`), not tags, and an instrument bubble splits its tag into
 * letters and number (`LIA`, `4107`): a `?select=LIA-4107` link (from the cause & effect matrix)
 * is matched against each group's own label texts, with case and punctuation left out.
 */

const norm = (text: string): string => text.replace(/[^0-9a-z]/gi, "").toUpperCase();

/** The texts of `group` that are not inside a nested representation group. */
function ownTexts(group: Element): string[] {
  return Array.from(group.querySelectorAll("text"))
    .filter((t) => t.closest(".representation-group") === group)
    .map((t) => (t.textContent ?? "").trim())
    .filter(Boolean);
}

/**
 * The representation group drawn for `tag` under `root`: the first whose own labels read the
 * tag (one text, or all of them joined: `LIA` + `4107`), else the first whose id is the tag
 * without punctuation (`P4101A`) or with an `Inst_` prefix. Null when the sheet does not draw it.
 */
export function findTagGroup(root: ParentNode, tag: string): Element | null {
  const wanted = norm(tag);
  if (!wanted) return null;
  const groups = Array.from(root.querySelectorAll(".representation-group[id]"));
  for (const group of groups) {
    const texts = ownTexts(group);
    if (!texts.length) continue;
    if (texts.some((t) => norm(t) === wanted) || norm(texts.join("")) === wanted) return group;
  }
  return groups.find((g) => norm(g.id) === wanted || norm(g.id.replace(/^Inst_/i, "")) === wanted) ?? null;
}
