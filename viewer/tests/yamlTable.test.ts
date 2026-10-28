import { describe, expect, it } from "vitest";
import type { JsonSchema } from "@/api";
import { cellText, typeSummary, yamlTable } from "@/lib/yamlTable";

// What pydantic emits for chemeascode.schemas.EquipmentList.
const equipmentSchema: JsonSchema = {
  $defs: {
    EquipmentItem: {
      additionalProperties: false,
      properties: {
        tag: { title: "Tag", type: "string" },
        type: { description: "DEXPI class.", title: "Type", type: "string" },
        service: { default: "", title: "Service", type: "string" },
        sheet: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Sheet" },
        design_pressure_barg: { anyOf: [{ type: "number" }, { type: "null" }], default: null, title: "Design Pressure Barg" },
      },
      required: ["tag", "type"],
      title: "EquipmentItem",
      type: "object",
    },
  },
  properties: { equipment: { items: { $ref: "#/$defs/EquipmentItem" }, title: "Equipment", type: "array" } },
  title: "EquipmentList",
  type: "object",
};

describe("yamlTable", () => {
  it("uses schema columns in schema order for a list kind", () => {
    const table = yamlTable({
      kind: "equipment",
      schema: equipmentSchema,
      data: { equipment: [{ tag: "P-101", type: "CentrifugalPump", sheet: "P-01" }, { type: "Tank", tag: "T-1" }] },
    });
    expect(table).not.toBeNull();
    expect(table!.key).toBe("equipment");
    expect(table!.rows).toHaveLength(2);
    expect(table!.columns.map((c) => c.key)).toEqual(["tag", "type", "service", "sheet", "design_pressure_barg"]);
    const [tag, type, , sheet, pressure] = table!.columns;
    expect(tag).toMatchObject({ title: "Tag", required: true, type: "string", extra: false });
    expect(type?.description).toBe("DEXPI class.");
    expect(sheet).toMatchObject({ required: false, type: "string?" });
    expect(pressure?.type).toBe("number?");
  });

  it("appends keys that rows have but the schema does not list", () => {
    const table = yamlTable({ kind: "equipment", schema: equipmentSchema, data: { equipment: [{ tag: "A", type: "Tank", colour: "red" }] } });
    expect(table!.columns.at(-1)).toMatchObject({ key: "colour", extra: true });
  });

  it("shows an empty list kind with its schema columns", () => {
    const table = yamlTable({ kind: "equipment", schema: equipmentSchema, data: { equipment: [] } });
    expect(table!.key).toBe("equipment");
    expect(table!.rows).toHaveLength(0);
    expect(table!.columns).toHaveLength(5);
  });

  it("does not tabulate a document that only contains lists (design basis)", () => {
    const doc = { kind: "design_basis", schema: null, data: { feeds: [{ name: "MNb" }], capacity: "1 t/h" } };
    expect(yamlTable(doc)).toBeNull();
    expect(yamlTable({ ...doc, data: { feeds: [{ name: "MNb" }] } })).toBeNull();
  });

  it("derives columns from the rows without a schema", () => {
    const table = yamlTable({ kind: "lines", schema: null, data: { lines: [{ number: "L1", from: "P-1" }, { number: "L2", to: "T-1" }] } });
    expect(table!.columns.map((c) => c.key)).toEqual(["number", "from", "to"]);
    expect(table!.columns.every((c) => !c.extra)).toBe(true);
  });

  it("tabulates a bare list of objects", () => {
    const table = yamlTable({ kind: null, schema: null, data: [{ a: 1 }, { b: 2 }] });
    expect(table!.key).toBeNull();
    expect(table!.columns.map((c) => c.key)).toEqual(["a", "b"]);
  });

  it("returns null for documents that are not lists (shown as a tree)", () => {
    expect(yamlTable({ kind: "design_basis", schema: null, data: { capacity: { value: 1 }, notes: "x" } })).toBeNull();
    expect(yamlTable({ kind: null, schema: null, data: "just text" })).toBeNull();
    expect(yamlTable({ kind: null, schema: null, data: { a: [1, 2] } })).toBeNull();
    expect(yamlTable({ kind: null, schema: null, data: { a: [{ x: 1 }], b: 2 } })).toBeNull();
    expect(yamlTable({ kind: null, schema: null, data: { a: [{ x: 1 }] } })!.key).toBe("a");
  });
});

describe("typeSummary", () => {
  it("summarises unions, arrays and refs", () => {
    const root: JsonSchema = { $defs: { S: { type: "string" } } };
    expect(typeSummary({ type: "array", items: { $ref: "#/$defs/S" } }, root)).toBe("string[]");
    expect(typeSummary({ anyOf: [{ type: "integer" }, { type: "string" }, { type: "null" }] }, root)).toBe("number | string?");
    expect(typeSummary({ enum: ["a", "b"] }, root)).toBe("enum");
    expect(typeSummary({ type: ["string", "null"] }, root)).toBe("string?");
  });
});

describe("cellText", () => {
  it("formats values for cells", () => {
    expect(cellText(null)).toBe("");
    expect(cellText(undefined)).toBe("");
    expect(cellText(3.5)).toBe("3.5");
    expect(cellText(false)).toBe("false");
    expect(cellText(["a", "b"])).toBe("a, b");
    expect(cellText({ a: 1 })).toBe('{"a":1}');
  });
});
