/**
 * Which drawing shows a changed object. Most changed objects (nozzles, pipes, nodes, attributes)
 * have no `<g id>` of their own in the SVG; the server maps each to the drawn object around it
 * (`old_owner` / `new_owner`). Plant metadata maps to the title block (cheme render gives
 * it its Label's id); objects nothing is drawn for (loop functions) have no owner.
 */
import type { Change, SheetDiff } from "@/api";

type Owners = Pick<SheetDiff, "old_owner" | "new_owner">;

/** The drawn id showing `change` in the new revision, else the old one; `null` when not drawn. */
export function drawnId(diff: Owners, change: Change): string | null {
  return diff.new_owner?.[change.object_id] ?? diff.old_owner?.[change.object_id] ?? null;
}

/** The drawn id for `change` on one side, `null` when that side does not draw it. */
export function drawnIdOn(diff: Owners, change: Change, side: "old" | "new"): string | null {
  const owners = side === "old" ? diff.old_owner : diff.new_owner;
  return owners?.[change.object_id] ?? null;
}

/** Changes shown by the drawing with SVG id `id`: the object itself and everything drawn by it. */
export function changesForDrawn(diff: Owners, changes: Change[], id: string): Change[] {
  return changes.filter(
    (c) => c.object_id === id || diff.new_owner?.[c.object_id] === id || diff.old_owner?.[c.object_id] === id,
  );
}

/**
 * The plant item a changed object belongs to (a nozzle's pump, a label's equipment), from the
 * server's `item` and `items`; `null` when there is none or the object is the item itself.
 */
export function plantItem(
  diff: Pick<SheetDiff, "items">,
  change: Change,
): { id: string; class: string; tag: string } | null {
  if (!change.item || change.item === change.object_id) return null;
  const info = diff.items?.[change.item];
  return { id: change.item, class: info?.class ?? "", tag: info?.tag ?? "" };
}

/** The sentence shown instead of the change table when it is empty. */
export function emptyChangesText(diff: Pick<SheetDiff, "status" | "old_svg" | "new_svg" | "new_rev" | "old_rev">): string {
  const status = diff.status || (diff.old_svg && !diff.new_svg ? "removed" : !diff.old_svg && diff.new_svg ? "added" : "");
  if (status === "added") return `Sheet added in ${diff.new_rev}.`;
  if (status === "removed") return `Sheet removed in ${diff.new_rev}.`;
  return "No changes between these revisions.";
}
