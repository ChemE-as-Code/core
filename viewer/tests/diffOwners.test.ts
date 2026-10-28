import { describe, expect, it } from "vitest";
import type { Change, SheetDiff } from "@/api";
import { changesForDrawn, drawnId, drawnIdOn, emptyChangesText, plantItem } from "@/lib/diffOwners";
import diffJson from "./fixtures/api/diff-bfd.json";

const change = (object_id: string, kind: Change["kind"] = "added"): Change => ({
  kind,
  object_type: "X",
  object_id,
  tag: null,
  domain: "conceptual",
  detail: "",
});

const diff = {
  old_owner: { Valve1: "Valve1", Nozzle9: "Pump9" },
  new_owner: { Pump1: "Pump1", Nozzle1: "Pump1", Pipe1: "PipingNetworkSystem1", Valve1: "Valve1" },
};

describe("diff owners", () => {
  it("maps a change to the drawing that shows it, new side first", () => {
    expect(drawnId(diff, change("Nozzle1"))).toBe("Pump1");
    expect(drawnId(diff, change("Nozzle9", "removed"))).toBe("Pump9");
    expect(drawnId(diff, change("PlantMetaData1", "modified"))).toBeNull();
    expect(drawnIdOn(diff, change("Nozzle9"), "new")).toBeNull();
    expect(drawnIdOn(diff, change("Nozzle9"), "old")).toBe("Pump9");
  });

  it("lists every change drawn by a picked object", () => {
    const changes = [change("Pump1"), change("Nozzle1"), change("Pipe1"), change("PlantMetaData1", "modified")];
    expect(changesForDrawn(diff, changes, "Pump1").map((c) => c.object_id)).toEqual(["Pump1", "Nozzle1"]);
    expect(changesForDrawn(diff, changes, "PipingNetworkSystem1").map((c) => c.object_id)).toEqual(["Pipe1"]);
  });

  it("works without owner maps (older servers)", () => {
    expect(drawnId({}, change("Pump1"))).toBeNull();
    expect(changesForDrawn({}, [change("Pump1"), change("Nozzle1")], "Pump1")).toHaveLength(1);
  });

  it("says when a sheet was added or removed instead of 'no changes'", () => {
    const base = { old_rev: "HEAD", new_rev: "working tree", old_svg: "", new_svg: "<svg/>" };
    expect(emptyChangesText({ ...base, status: "added" })).toBe("Sheet added in working tree.");
    expect(emptyChangesText({ ...base })).toBe("Sheet added in working tree.");
    expect(emptyChangesText({ ...base, old_svg: "<svg/>", new_svg: "", status: "removed" })).toBe(
      "Sheet removed in working tree.",
    );
    expect(emptyChangesText({ ...base, old_svg: "<svg/>", status: "" })).toBe("No changes between these revisions.");
  });
});

describe("plantItem", () => {
  it("names the plant item a changed object belongs to, from the real /api/diff", () => {
    const diff = diffJson as unknown as SheetDiff;
    const title = diff.changes.find((c) => c.object_id === "Label_title")!;
    expect(plantItem(diff, title)).toEqual({ id: "ProcessModel_BFD", class: "ProcessModel", tag: "" });
    // an object that is its own item, and a change without item (an older server)
    const own = diff.changes.find((c) => c.item === c.object_id)!;
    expect(plantItem(diff, own)).toBeNull();
    expect(plantItem({}, change("Nozzle1"))).toBeNull();
    expect(plantItem({}, { ...change("Nozzle1"), item: "Pump1" })).toEqual({ id: "Pump1", class: "", tag: "" });
  });
});
