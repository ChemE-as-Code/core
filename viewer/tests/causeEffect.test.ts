import { describe, expect, it } from "vitest";
import type { InterlockMatrix, Sheet, TreeEntry } from "@/api";
import { actionTone, cellActions, cellKey, cellTone, compareMatrix, hasInterlocks, matrixCsv, tagSheets } from "@/lib/causeEffect";
import { findTagGroup } from "@/lib/pidTag";
// The real /api/interlocks of the ASU (scripts/regen-fixtures.py --asu).
import asuJson from "./fixtures/api/interlocks-asu.json";

const asu = asuJson as unknown as InterlockMatrix;
const sheets: Sheet[] = [
  { id: "P-01", file: "pid/P-01.xml", title: "Air compression" },
  { id: "P-04", file: "pid/P-04.xml", title: "Product storage" },
];

/** A copy of the ASU matrix with `edit` applied to its rows (cells by column). */
function edited(edit: (rows: InterlockMatrix["rows"], columns: string[]) => void): InterlockMatrix {
  const copy = JSON.parse(JSON.stringify(asu)) as InterlockMatrix;
  edit(copy.rows, copy.columns);
  return copy;
}

describe("hasInterlocks", () => {
  it("looks for the file core reads", () => {
    const tree: TreeEntry[] = [
      { path: "control", type: "dir", kind: "other" },
      { path: "control/instrument-list.yaml", type: "file", kind: "yaml" },
    ];
    expect(hasInterlocks(tree)).toBe(false);
    expect(hasInterlocks([...tree, { path: "control/cause-effect.yaml", type: "file", kind: "yaml" }])).toBe(true);
    expect(hasInterlocks([{ path: "processes/asu-1/control/cause-effect.yaml", type: "file", kind: "yaml" }])).toBe(false);
  });
});

describe("actionTone", () => {
  it("groups core's actions", () => {
    expect(["trip", "stop", "close", "depressurize"].map((a) => actionTone(a))).toEqual(["stop", "stop", "stop", "stop"]);
    expect(actionTone("open")).toBe("start");
    expect(actionTone("start")).toBe("start");
    expect(actionTone("alarm")).toBe("alarm");
    expect(actionTone("")).toBeNull();
  });
});

describe("cells with several actions (pre-release PR 269)", () => {
  it("splits a cell on ' + ' in core's order", () => {
    expect(cellActions("close + alarm")).toEqual(["close", "alarm"]);
    expect(cellActions("trip")).toEqual(["trip"]);
    expect(cellActions("")).toEqual([]);
  });
  it("takes the tone of the most severe action", () => {
    expect(cellTone("close + alarm")).toBe("stop");
    expect(cellTone("alarm + close")).toBe("stop");
    expect(cellTone("alarm + open")).toBe("start");
    expect(cellTone("open + trip + alarm")).toBe("stop");
    expect(cellTone("alarm")).toBe("alarm");
    expect(cellTone("close")).toBe("stop");
    expect(cellTone("")).toBeNull();
  });
});

describe("tagSheets", () => {
  it("puts the causes and effects of the ASU on P-04", () => {
    const map = tagSheets(asu, sheets);
    expect(map.get("LIA-4107")).toBe("pid/P-04.xml");
    expect(map.get("P-4101A")).toBe("pid/P-04.xml");
    expect(map.get("XV-4137")).toBe("pid/P-04.xml");
    expect(map.size).toBe(2 + asu.columns.length);
  });

  it("leaves out tags of an interlock without a known sheet; an effect takes the first sheet acting on it", () => {
    const matrix = edited((rows) => {
      rows[0]!.sheet = null;
      rows[1]!.sheet = "pid/P-09.xml"; // a file path not in plant.yaml still works
    });
    matrix.rows[1]!.cells[0] = "alarm"; // I-02 also acts on P-4101A
    const map = tagSheets(matrix, sheets);
    expect(map.has("LIA-4107")).toBe(false);
    expect(map.has("XV-4136")).toBe(false);
    expect(map.get("P-4101A")).toBe("pid/P-09.xml");
    expect(map.get("LIA-4108")).toBe("pid/P-09.xml");
    expect(tagSheets(edited((rows) => (rows[1]!.sheet = "P-99")), sheets).has("LIA-4108")).toBe(false);
  });
});

describe("compareMatrix", () => {
  it("finds nothing between a revision and itself", () => {
    const diff = compareMatrix(asu, asu);
    expect(diff.same).toBe(true);
    expect(diff.cells.size).toBe(0);
  });

  it("marks changed cells with the other revision's action, and changed fields", () => {
    const now = edited((rows) => {
      rows[0]!.cells[2] = "open"; // XV-4136 opens instead of closing
      rows[0]!.cells[3] = "alarm"; // and I-01 now alarms on P-4102A
      rows[1]!.sil = 1;
      rows[1]!.condition = "LL";
    });
    const diff = compareMatrix(now, asu);
    expect(diff.same).toBe(false);
    expect([...diff.cells.entries()]).toEqual([
      [cellKey("I-01", "XV-4136"), "close"],
      [cellKey("I-01", "P-4102A"), ""],
    ]);
    expect(diff.changedFields.get("I-02")).toEqual(["condition", "sil"]);
    expect(diff.changedFields.has("I-01")).toBe(false);
    expect(diff.addedRows.size).toBe(0);
  });

  it("marks a cell whose set of actions changed, not one only listed in another order", () => {
    const older = edited((rows) => (rows[0]!.cells[2] = "close + alarm")); // XV-4136 closed and alarmed
    expect([...compareMatrix(asu, older).cells.entries()]).toEqual([[cellKey("I-01", "XV-4136"), "close + alarm"]]);
    expect([...compareMatrix(older, asu).cells.entries()]).toEqual([[cellKey("I-01", "XV-4136"), "close"]]);
    const reordered = edited((rows) => (rows[0]!.cells[2] = "alarm + close"));
    expect(compareMatrix(reordered, older).same).toBe(true);
    const other = edited((rows) => (rows[0]!.cells[2] = "close + stop"));
    expect([...compareMatrix(other, older).cells.keys()]).toEqual([cellKey("I-01", "XV-4136")]);
  });

  it("lists added and removed interlocks, and actions on tags this revision no longer has", () => {
    const older: InterlockMatrix = {
      ...asu,
      columns: [...asu.columns, "PV-4111"],
      rows: [
        { ...asu.rows[0]!, cells: [...asu.rows[0]!.cells, "close"] },
        { id: "I-00", title: "Old trip", cause: "TSLL-4113", condition: "TSLL", sheet: "P-04", sil: null, cells: [...asu.columns.map(() => "" as const), "close"] },
      ],
    };
    const diff = compareMatrix(asu, older);
    expect([...diff.addedRows]).toEqual(["I-02"]);
    expect(diff.removedRows.map((r) => r.id)).toEqual(["I-00"]);
    expect(diff.removedCells).toEqual([{ row: "I-01", column: "PV-4111", action: "close" }]);
    // the new interlock's actions are all changes (from none)
    expect([...diff.cells.keys()].filter((k) => k.startsWith("I-02"))).toHaveLength(3);
  });
});

describe("matrixCsv", () => {
  it("writes what cheme cause-effect writes", () => {
    expect(matrixCsv(asu)).toBe(
      "id,cause,condition,sheet,sil,P-4101A,P-4101B,XV-4136,P-4102A,P-4102B,XV-4137\n" +
        "I-01,LIA-4107,LALL,P-04,,trip,trip,close,,,\n" +
        "I-02,LIA-4108,LALL,P-04,,,,,trip,trip,close\n",
    );
  });
  it("writes a cell with several actions as core does", () => {
    expect(matrixCsv(edited((rows) => (rows[0]!.cells[2] = "close + alarm")))).toContain("I-01,LIA-4107,LALL,P-04,,trip,trip,close + alarm,,,\n");
  });
  it("quotes fields with commas", () => {
    expect(matrixCsv(edited((rows) => (rows[0]!.condition = "LALL, 2oo3")))).toContain('I-01,LIA-4107,"LALL, 2oo3",');
  });
});

describe("findTagGroup", () => {
  // As cheme render draws the ASU's P-04: DEXPI ids on the groups, the tags in their labels.
  document.body.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg"><g id="pid-layer">
    <g id="P4101A" class="representation-group">
      <g class="static"><circle r="5"/></g>
      <g id="P4101A_N1" class="representation-group"><text>N1</text></g>
      <g class="equipmenttagnamelabel"><text>P-4101A</text></g>
    </g>
    <g id="Inst_LIA4107" class="representation-group">
      <g class="processinstrumentationfunctionlabel"><text>LIA</text><text>4107</text></g>
      <g id="Inst_LIA4107_ML" class="representation-group"/>
    </g>
    <g id="XV4136" class="representation-group"><g class="static"/></g>
    <g id="L1" class="representation-group"><text>see C&amp;E I-01</text><text>P-4101B suction</text></g>
  </g></svg>`;
  const root = document.getElementById("pid-layer")!;

  it("finds equipment and instruments by their labels", () => {
    expect(findTagGroup(root, "P-4101A")?.id).toBe("P4101A");
    expect(findTagGroup(root, "LIA-4107")?.id).toBe("Inst_LIA4107");
    expect(findTagGroup(root, "lia 4107")?.id).toBe("Inst_LIA4107");
  });
  it("falls back to an id that is the tag without punctuation", () => {
    expect(findTagGroup(root, "XV-4136")?.id).toBe("XV4136");
  });
  it("does not match a tag inside a longer label, or a tag the sheet lacks", () => {
    expect(findTagGroup(root, "P-4101B")).toBeNull();
    expect(findTagGroup(root, "P-4102A")).toBeNull();
    expect(findTagGroup(root, "")).toBeNull();
  });
});
