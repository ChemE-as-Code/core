/**
 * Scene building from the generated model: the real ASU `/api/layout` (core's frozen fixture,
 * every section of the contract filled) and small hand-made models for the geometry rules.
 */
import { describe, expect, it } from "vitest";
import type { Finding, Layout, LayoutModel, ModelPenetration, Sheet } from "@/api";
import { buildScene, cameraPose, findingTargets, resolveSelect } from "@/lib/layoutScene";
import {
  boxEdges,
  buildModelScene,
  EYE_HEIGHT,
  floorsAt,
  insideSection,
  lighten,
  measure,
  odOf,
  partPrim,
  pipeRun,
  pipeService,
  polylineLength,
  primBounds,
  PROVENANCE_COLORS,
  provenanceColor,
  repoSheet,
  REVIEW_COLOR,
  sectionFromFractions,
  sectionPlanes,
  serviceColor,
  snapFloor,
  stepFloor,
  volumePrim,
  zoneColor,
  type Floor,
} from "@/lib/layoutModel";
import { DEFAULT_SHOWN, layoutQuery, parseLayoutQuery } from "@/lib/layoutUrl";
import asuJson from "./fixtures/layout-asu.json";
import penetrationJson from "./fixtures/layout-asu-penetration.json";

const asu = asuJson as unknown as Layout;
const model = asu.model!;
// The ASU declares all its casing openings (process-library#4), so its model has no sleeve: the
// penetration and its finding from a copy without the opening AIR-2002 (scripts/regen-fixtures.py).
const opened = penetrationJson as unknown as { model: Required<Pick<LayoutModel, "penetrations">>; model_findings: Finding[] };
const withPenetration: Layout = { ...asu, model: { ...model, penetrations: opened.model.penetrations }, model_findings: [...(asu.model_findings ?? []), ...opened.model_findings] };
// The repo's sheet list, as /api/repo would give it: every sheet the model's refs name (P-01..P-04).
const sheetFiles = [...new Set([...model.pipes, ...model.inline, ...model.equipment].map((o) => o.refs.sheet).filter((f): f is string => Boolean(f)))].sort();
const sheets: Sheet[] = sheetFiles.map((file) => ({ id: file.replace(/^.*\//, "").replace(/\.xml$/, ""), file, title: "", kind: "pid" }));
const scene = buildScene(asu, { sheets });

const close = (actual: number[], expected: number[], digits = 6) => expected.forEach((v, i) => expect(actual[i]).toBeCloseTo(v, digits));

describe("the ASU model", () => {
  const nozzles = model.equipment.flatMap((e) => e.nozzles);
  // A nozzle's own detail (`<tag>/<nozzle>/neck|flange|...`) is drawn with the nozzle.
  const nozzleIds = new Set(nozzles.map((n) => n.id));
  const ownerOf = (id: string) => id.slice(0, id.lastIndexOf("/"));
  const allParts = model.equipment.flatMap((e) => e.parts);
  const parts = allParts.filter((p) => !nozzleIds.has(ownerOf(p.id)));
  const nozzleParts = allParts.filter((p) => nozzleIds.has(ownerOf(p.id)));
  const envelopes = model.equipment.flatMap((e) => e.envelopes);

  it("shows a proposed valve access platform and proposed support steel as items to review and pin", () => {
    const vp = model.structures.find((s) => s.review_needed)!;
    const platform = scene.items.get(`structure:${vp.id}`)!;
    expect(platform).toMatchObject({ kind: "structure", type: "valve access platform", review: true });
    const details = Object.fromEntries(platform.details);
    expect(details).toMatchObject({ serves: vp.serves!.join(", "), why: vp.reason, "to keep it": `cheme layout pin ${vp.id}` });
    // its stair or ladder belongs to it: no access proposal of its own
    for (const way of [...vp.stairs, ...vp.ladders]) expect(resolveSelect(way.id, scene)).toBe(`structure:${vp.id}`);
    expect(scene.meshes.filter((m) => m.item === `structure:${vp.id}`).every((m) => m.review)).toBe(true);
    expect(scene.proposals.get("valve platform")).toEqual(model.structures.filter((s) => s.review_needed).map((s) => `structure:${s.id}`));
    // the ASU declares most of its posts (pinned proposals); the rest are proposals to review
    const proposedPosts = (model.support_steel ?? []).filter((s) => s.review_needed);
    const post = proposedPosts[0]!;
    const steel = scene.items.get(`support:${post.id}`)!;
    expect(steel).toMatchObject({ kind: "support", type: "support steel", review: true, related: [{ key: `pipe:${post.serves![0]}`, label: post.serves![0] }] });
    expect(Object.fromEntries(steel.details)["to keep it"]).toBe(`cheme layout pin ${post.id}`);
    expect(scene.proposals.get("support steel")).toHaveLength(proposedPosts.length);
    const declared = (model.support_steel ?? []).find((s) => !s.review_needed)!;
    expect(scene.items.get(`support:${declared.id}`)).toMatchObject({ kind: "support", review: false });
    expect(Object.fromEntries(scene.items.get(`support:${declared.id}`)!.details)["to keep it"]).toBeUndefined();
  });

  it("draws every equipment part, and no placement primitive for modelled items", () => {
    const equipment = scene.meshes.filter((m) => m.layer === "equipment");
    expect(equipment).toHaveLength(parts.length);
    expect(parts.length).toBeGreaterThan(model.equipment.length);
    expect(scene.solids.filter((s) => s.layer === "equipment")).toEqual([]);
    expect(scene.hasModel).toBe(true);
    // Each part's material, and the shell in the item's type colour.
    expect(new Set(equipment.map((m) => m.material))).toEqual(new Set(parts.map((p) => p.material)));
    expect(new Set(equipment.map((m) => m.material))).toEqual(expect.objectContaining(new Set(["casing", "motor", "shell", "steel", "concrete", "guard", "flange"])));
    const column = equipment.filter((m) => m.item === "equipment:C-1101");
    // The envelope at every distance, the detail (foundation, base ring, anchor chairs, ...) close up.
    // The shell, its heads and the top-head davit (post and arm: steel the pipes keep clear of).
    expect(column.filter((m) => m.lod === undefined).map((m) => m.prim.kind)).toEqual(["cylinder", "cap", "cylinder", "cap", "cylinder", "cylinder"]);
    expect(column.filter((m) => m.lod === undefined).slice(4).map((m) => m.key)).toEqual(["C-1101/davit-post", "C-1101/davit-arm"]);
    expect(column.filter((m) => m.lod === 2).length).toBeGreaterThan(5);
    expect(column.find((m) => m.key === "C-1101/shell")?.color).toBe("#e0861a");
    // Machines: an envelope from afar and detail close up.
    const pump = equipment.filter((m) => m.item === "equipment:P-1101A");
    expect(pump.some((m) => m.lod === 1) && pump.some((m) => m.lod === 2)).toBe(true);
    expect(pump.some((m) => m.prim.kind === "torus")).toBe(true);
  });

  it("gives each nozzle a stub and a flange, and each envelope a translucent box with edges", () => {
    expect(nozzles.length).toBe(162);
    // A transmitter declared remote-mounted leaves its tapping for a stand the viewer draws.
    const remote = new Set(nozzles.filter((n) => n.operator?.kind === "remote_mount").map((n) => n.id));
    expect(remote.size).toBe(11);
    const head = /\/(transmitter|transmitter-cap|bracket)$/;
    const kept = nozzleParts.filter((p) => !(remote.has(ownerOf(p.id)) && head.test(p.id)));
    const nozzleMeshes = scene.meshes.filter((m) => m.layer === "nozzles");
    expect(nozzleMeshes.filter((m) => !m.key.includes(":remote:"))).toHaveLength(2 * nozzles.length + kept.length);
    expect(new Set(nozzleMeshes.filter((m) => m.key.includes(":remote:")).map((m) => m.item))).toEqual(new Set([...remote].map((id) => `nozzle:${id}`)));
    expect(scene.meshes.filter((m) => m.layer === "envelopes")).toHaveLength(envelopes.length);
    expect(scene.edges.filter((e) => e.layer === "envelopes")).toHaveLength(envelopes.length);
    expect(scene.edges[0]!.segments).toHaveLength(12);
    const n1 = model.equipment.find((e) => e.tag === "F-1101")!.nozzles[0]!;
    const stub = scene.meshes.find((m) => m.key === `nozzle:${n1.id}`)!;
    expect(stub.prim.kind).toBe("cylinder");
    if (stub.prim.kind === "cylinder") {
      // From where the neck leaves the shell to the flange face, where the pipe connects.
      expect(stub.prim.end).toEqual(n1.point);
      if (n1.base) expect(stub.prim.start).toEqual(n1.base);
      expect(stub.prim.end[0]).toBeGreaterThan(stub.prim.start[0]);
    }
    // With core's neck and flange, the stub is the envelope.
    if (nozzleParts.some((p) => ownerOf(p.id) === n1.id)) expect(stub.lod).toBe(1);
  });

  it("starts with every layer but the envelopes on", () => {
    expect(DEFAULT_SHOWN).not.toContain("envelopes");
    expect(DEFAULT_SHOWN).toEqual(expect.arrayContaining(["equipment", "nozzles", "pipes", "labels"]));
  });

  it("draws everything the model has: every pipe, in-line item, platform, structure and zone", () => {
    const itemsOf = (kind: string) => [...scene.items.keys()].filter((k) => k.startsWith(`${kind}:`));
    const drawn = new Set(scene.meshes.map((m) => m.item));
    const count = (kind: string) => itemsOf(kind).filter((k) => drawn.has(k)).length;
    expect(model.pipes).toHaveLength(model.routing.routed);
    expect(count("pipe")).toBe(model.pipes.length);
    // Each pipe says why the router took its route.
    for (const p of model.pipes) expect(Object.fromEntries(scene.items.get(`pipe:${p.id}`)!.details).reason, p.id).toBe(p.reason);
    // A component two segments share comes once, with both segments in its refs: one item between both pipes.
    expect(count("inline")).toBe(model.inline.length);
    for (const i of model.inline) expect(scene.items.get(`inline:${i.id}`)?.related?.map((r) => r.key)).toContain(`pipe:${i.pipe}`);
    expect(model.platforms.length).toBeGreaterThan(0);
    // Platforms, the proposed step-overs, and the proposed stairs and ladders (of the frames and racks).
    const proposedAccess = [...model.structures.filter((s) => !s.review_needed).flatMap((s) => [...s.stairs, ...s.ladders]), ...model.racks.flatMap((r) => r.ladders ?? [])].filter((x) => x.review_needed);
    expect(proposedAccess.length).toBeGreaterThan(0);
    expect(count("platform")).toBe(model.platforms.length + (model.step_overs ?? []).length + proposedAccess.length);
    // A sleeve where each pipe passes a wall outside its openings (none in the ASU, one in the copy without AIR-2002).
    expect(count("penetration")).toBe((model.penetrations ?? []).length);
    const opened = buildScene(withPenetration, { sheets });
    expect([...opened.items.keys()].filter((k) => k.startsWith("penetration:"))).toEqual(["penetration:CB-1/AIR-2002"]);
    // The cold box frame, the fire walls (the compressor's and the transformers') and the
    // declared valve access platforms (pinned VP-<n>),
    const declaredVp = model.structures.filter((s) => s.id.startsWith("VP-") && !s.review_needed).map((s) => s.id);
    expect(declaredVp.length).toBeGreaterThan(0);
    expect(model.structures.filter((s) => !s.review_needed).map((s) => s.id)).toEqual(["CB-1", "FW-TR", "FW-4101", ...declaredVp]);
    // and the valve access platforms the build proposes (VP-<n>), one item each with its ways
    expect(model.structures.filter((s) => s.review_needed).map((s) => s.id)).toEqual(model.structures.filter((s) => s.id.startsWith("VP-") && !declaredVp.includes(s.id)).map((s) => s.id));
    expect(count("structure")).toBe(model.structures.length);
    // posts and T-posts under pipes (declared, or proposals to review), each an item
    expect((model.support_steel ?? []).length).toBeGreaterThan(0);
    expect(count("support")).toBe((model.support_steel ?? []).length);
    expect(model.zones.length).toBeGreaterThan(3);
    expect(count("zone")).toBe(model.zones.length);
    expect(count("equipment")).toBe(model.equipment.length);
    // Every part of every object is a mesh, each under its own id.
    const partIds = [
      ...model.racks.flatMap((r) => r.parts),
      ...model.buildings.flatMap((b) => b.parts),
      ...model.structures.flatMap((s) => [...s.parts, ...s.walls, ...s.stairs.flatMap((t) => t.parts), ...s.ladders.flatMap((l) => l.parts)]),
      ...model.platforms.flatMap((p) => [...p.parts, ...p.ladder.parts]),
      ...model.racks.flatMap((r) => (r.ladders ?? []).flatMap((l) => l.parts)),
      ...model.areas.flatMap((a) => a.parts ?? []),
      ...model.pipes.flatMap((p) => p.parts ?? []),
      ...(model.supports ?? []).flatMap((s) => s.parts),
      ...(model.step_overs ?? []).flatMap((s) => s.parts),
      ...allParts,
    ].map((p) => p.id);
    const keys = new Set(scene.meshes.map((m) => m.key));
    // All but the transmitter heads of the remote-mounted tappings: those stand on their stands.
    const remote = new Set(model.equipment.flatMap((e) => e.nozzles).filter((n) => n.operator?.kind === "remote_mount").map((n) => n.id));
    const headOfRemote = (id: string) => remote.has(id.slice(0, id.lastIndexOf("/"))) && /\/(transmitter|transmitter-cap|bracket)$/.test(id);
    expect(partIds.filter((id) => !keys.has(id) && !headOfRemote(id))).toEqual([]);
    expect(partIds.filter(headOfRemote)).toHaveLength(3 * remote.size);
    // Every zone volume.
    expect(scene.meshes.filter((m) => m.layer === "zones")).toHaveLength(model.zones.flatMap((z) => z.volumes).length);
    // Gratings, handrails and ladder cages go on the platforms layer, the frame on the structures layer.
    expect(new Set(scene.meshes.filter((m) => m.layer === "platforms").map((m) => m.material))).toEqual(new Set(["grating", "handrail", "cage", "steel"]));
    // Core's valve bodies and operators replace the viewer's own shapes.
    const valve = model.inline.find((i) => i.parts?.length)!;
    expect(scene.meshes.filter((m) => m.item === `inline:${valve.id}` && !m.key.includes(":operator:"))).toHaveLength(valve.parts!.length);
    expect(scene.meshes.find((m) => m.key.startsWith("CB-1/col-"))?.layer).toBe("structures");
    // The model's rack steel replaces the frame drawn from the centreline.
    expect(scene.lines.filter((l) => l.key.startsWith("rack:"))).toEqual([]);
  });

  it("links the in-line items to their pipes and the stairs and ladders to their frame", () => {
    for (const i of model.inline) expect(scene.items.has(`pipe:${i.pipe}`), i.id).toBe(true);
    const cb = scene.items.get("structure:CB-1")!;
    const frame = model.structures.find((s) => s.id === "CB-1")!;
    expect(Object.fromEntries(cb.details)).toMatchObject({
      size: "15 x 9 x 53 m",
      parts: String(frame.parts.length),
      ladders: `${frame.ladders.length} (caged)`,
      walls: String(frame.walls.length),
      sections: "beam HEB400, brace L100x10, column HEB400 (ASSUMED)",
    });
    for (const stair of Object.fromEntries(cb.details).stairs!.split("; ")) expect(stair).toMatch(/^[\w-]+ to [\w-]+ \(\d+ flights, \w+\)$/);
    expect(resolveSelect(model.structures[0]!.stairs[0]!.id, scene)).toBe("structure:CB-1");
  });

  it("marks every model object generated or declared, and what to review", () => {
    const sources = new Set(scene.meshes.map((m) => m.source));
    expect(sources).toEqual(new Set(["generated", "declared", "pinned"]));
    // Pinned: only what the model says is pinned (the ASU pins three pipe routes).
    const pinned = new Set(scene.meshes.filter((m) => m.source === "pinned").map((m) => m.item));
    expect(pinned).toEqual(new Set(model.pipes.filter((p) => p.source === "pinned").map((p) => `pipe:${p.id}`)));
    expect(provenanceColor("generated")).toBe(PROVENANCE_COLORS.generated);
    expect(provenanceColor("pinned")).toBe(PROVENANCE_COLORS.pinned);
    expect(provenanceColor(null)).toBe(PROVENANCE_COLORS.unknown);
    // The direct routes, the proposed platforms, stairs, ladders, step-overs and wall openings, and nothing else.
    const review = new Set(scene.meshes.filter((m) => m.review).map((m) => m.item));
    const access = [...model.structures.filter((s) => !s.review_needed).flatMap((s) => [...s.stairs, ...s.ladders]), ...model.racks.flatMap((r) => r.ladders ?? [])];
    const expected = [
      ...model.pipes.filter((p) => p.review_needed).map((p) => `pipe:${p.id}`),
      ...model.platforms.filter((p) => p.review_needed).map((p) => `platform:${p.id}`),
      ...access.filter((x) => x.review_needed).map((x) => `platform:${x.id}`),
      ...(model.step_overs ?? []).filter((s) => s.review_needed).map((s) => `platform:${s.id}`),
      ...(model.penetrations ?? []).filter((p) => p.review_needed).map((p) => `penetration:${p.id}`),
      ...model.structures.filter((s) => s.review_needed).map((s) => `structure:${s.id}`),
      ...(model.support_steel ?? []).filter((s) => s.review_needed).map((s) => `support:${s.id}`),
    ];
    expect(expected.length).toBeGreaterThan(0);
    expect(review).toEqual(new Set(expected));
    // Each proposal is an item of its own: why, and how to keep it. The ASU has pinned its
    // stairs (process-library#2), so the first one is made a proposal again here.
    const proposedStair = { ...model.structures[0]!.stairs[0]!, source: "generated", review_needed: true, reason: "a stair for every level at 6 m or higher (ASSUMED)" } as (typeof model.structures)[number]["stairs"][number];
    const proposed = { ...model, structures: model.structures.map((st, i) => (i === 0 ? { ...st, stairs: [proposedStair, ...st.stairs.slice(1)] } : st)) };
    const proposedScene = buildScene({ ...asu, model: proposed }, { sheets });
    const stair = proposedStair;
    const proposal = proposedScene.items.get(`platform:${stair.id}`)!;
    expect(proposal).toMatchObject({ type: "stair", review: true, related: [{ key: "structure:CB-1", label: "CB-1" }] });
    expect(Object.fromEntries(proposal.details)).toMatchObject({ why: stair.reason, "to keep it": `cheme layout pin ${stair.id}` });
    expect(resolveSelect(stair.id, proposedScene)).toBe(`platform:${stair.id}`);
    // Listed for the review panel by what they are.
    expect(proposedScene.proposals.get("stair")).toEqual([`platform:${stair.id}`]);
    expect(scene.proposals.get("stair") ?? []).toEqual([]); // the ASU's own stairs are declared
    expect(scene.proposals.get("penetration") ?? []).toHaveLength((model.penetrations ?? []).length);
    expect(buildScene(withPenetration, { sheets }).proposals.get("penetration")).toEqual(["penetration:CB-1/AIR-2002"]);
    // A wall penetration says how to keep it; a roof penetration (pre-release PR 270) cannot be pinned, so
    // it says why with core's refusal, and gives its opening in the building's plan frame.
    const wall = buildScene(withPenetration, { sheets }).items.get("penetration:CB-1/AIR-2002")!;
    expect(Object.fromEntries(wall.details)).toMatchObject({
      wall: "CB-1/wall-north-12",
      "opening needed": "0.65 x 0.65 m, north side, 7.75 m along, sill 7.95 m",
      "to keep it": "cheme layout pin CB-1/AIR-2002",
    });
    const [cased] = opened.model.penetrations!;
    const roofPen = {
      ...cased!,
      id: "B1/AIR-2002",
      owner: "B1",
      wall: "B1/roof",
      point: [41.2, 27.5, 12.3],
      material: "",
      length: 1.4,
      opening: { side: "roof", offset: 4.6, width: 2.15, height: 0.75, sill: 5.1, kind: "opening" },
      reason: "through the roof of building B1: a roof penetration, running 1.4 m in the roof slab",
    } as ModelPenetration;
    const roofScene = buildScene({ ...asu, model: { ...model, penetrations: [roofPen] } }, { sheets });
    const roofItem = roofScene.items.get("penetration:B1/AIR-2002")!;
    const roofDetails = Object.fromEntries(roofItem.details);
    expect(roofDetails).toMatchObject({
      roof: "B1/roof",
      "in the roof slab": "1.4 m",
      "opening needed": "2.15 x 0.75 m in the roof, x 4.6 to 6.75 m and y 5.1 to 5.85 m from B1's origin corner",
      "cannot be pinned": "B1/AIR-2002 is a roof penetration: a roof opening cannot be declared; route the line into B1 through a wall (via points) and pin that opening",
    });
    expect(roofDetails).not.toHaveProperty("to keep it");
    expect(roofItem.details.some(([, v]) => v.includes("cheme layout pin"))).toBe(false);
    expect(roofItem.related?.map((r) => r.key)).toContain("building:B1");
    expect(roofScene.proposals.get("penetration")).toEqual(["penetration:B1/AIR-2002"]);
    // "review needed" is in the legend only when something is to review (the ASU: the access proposals).
    expect(scene.legend.provenance).toEqual([
      { label: "generated", color: PROVENANCE_COLORS.generated },
      { label: "pinned", color: PROVENANCE_COLORS.pinned },
      { label: "declared", color: PROVENANCE_COLORS.declared },
      ...(expected.length ? [{ label: "review needed", color: REVIEW_COLOR }] : []),
    ]);
    expect(scene.items.get("platform:C-1101/platform-1")?.review).toBe(Boolean(model.platforms.find((p) => p.id === "C-1101/platform-1")?.review_needed));
    expect(scene.items.get("equipment:C-1101")?.review).toBeFalsy();
    // A fallback route in a model that has one.
    const withDirect = buildModelScene({ ...model, pipes: model.pipes.map((p, i) => (i === 0 ? { ...p, review_needed: true } : p)) }, { sheets });
    expect(withDirect.items.get(`pipe:${model.pipes[0]!.id}`)?.review).toBe(true);
  });

  it("points every model finding at the objects it names, with its 3D box", () => {
    const findings = asu.model_findings!;
    expect(findings.length).toBeGreaterThan(0);
    // Every finding marks objects (no repeats) and its box; ids that are no object (`grade`, a
    // walking level) are left to the box.
    const notObjects = new Set(["grade"]);
    for (const f of findings) {
      const targets = findingTargets(f, scene);
      const what = `${f.rule} ${f.ids.join(", ")}`;
      expect(new Set(targets.items).size, what).toBe(targets.items.length);
      expect(targets.items.length, what).toBeGreaterThan(0);
      for (const id of f.ids) if (!notObjects.has(id)) expect(resolveSelect(id, scene), `${what}: ${id}`).not.toBeNull();
      expect(targets.box, f.rule).not.toBeNull();
    }
    // The engineering rules' findings point at what they are about.
    const first = (rule: string) => findings.find((f) => f.rule === `cheme.layout-${rule}`)!;
    const kindsOf = (f: Finding, on = scene) => findingTargets(f, on).items.map((k) => k.slice(0, k.indexOf(":")));
    const kinds = (rule: string) => kindsOf(first(rule));
    expect(kinds("operability")).toEqual(["inline"]);
    expect(kinds("free-span")).toEqual(["pipe"]);
    // The ASU closed its tier, lifting, vent, escape and spacing findings (process-library#2, #4): the
    // same ids as core gives them, on the ASU's objects.
    const like = (rule: string, ids: string[]): Finding => {
      const { key: _key, ...finding } = first("operability");
      return { ...finding, rule: `cheme.layout-${rule}`, ids };
    };
    const zone = model.zones[0]!.id;
    const platform = model.platforms[0]!.id;
    const pipe = model.pipes.find((p) => p.racks?.length)!;
    expect(kindsOf(like("tier", [pipe.id, pipe.racks![0]!]))).toEqual(["pipe", "rack"]);
    expect(kindsOf(like("lifting", ["K-4101", "Z-PAD-A4", "P-03/Line_AIR3005_S1"]))).toEqual(["equipment", "zone", "pipe"]);
    expect(kindsOf(like("vent-outlet", [zone, "C-1101"]))).toEqual(["zone", "equipment"]);
    expect(kindsOf(like("escape-travel", [model.structures[0]!.id]))).toEqual(["structure"]);
    expect(kindsOf(like("escape-ways", [platform]))).toEqual(["platform"]);
    expect(kindsOf(like("spacing", ["P-1101A", "P-1101B"]))).toEqual(["equipment", "equipment"]);
    // The access rules of pre-release issue 61 (none left in the ASU), with the ids core gives: headroom over
    // a frame's stair or level, or an item's stair or roof as a whole (its item); stacked stairs and
    // their frame; a ladder's head in a zone; a declared operator naming nothing (no object).
    expect(kindsOf(like("headroom", ["P-03/Line_AIR3005_S1", "CB-1/ST1"]))).toEqual(["pipe", "structure"]);
    expect(findingTargets(like("headroom", ["P-03/Line_AIR3005_S1", "T-4101/stair"]), scene).items).toEqual(["pipe:P-03/Line_AIR3005_S1", "equipment:T-4101"]);
    expect(findingTargets(like("headroom", ["P-03/Line_AIR3005_S1", "T-4101/roof"]), scene).items).toEqual(["pipe:P-03/Line_AIR3005_S1", "equipment:T-4101"]);
    expect(kindsOf(like("landing-width", ["CB-1/ST2", "CB-1/ST3", "CB-1"]))).toEqual(["structure"]);
    expect(kindsOf(like("egress-zone", ["CB-1/LD4", "Z-N2-CASING"]))).toEqual(["structure", "zone"]);
    expect(findingTargets({ ...like("operator-unknown", ["XV-9999"]), key: "operator:XV-9999" }, scene).items).toEqual([]);
    // A wall penetration names its sleeve first, then the pipe and the wall's owner.
    const pen = opened.model_findings.find((f) => f.rule === "cheme.layout-wall-penetration")!;
    const penScene = buildScene(withPenetration, { sheets });
    const penTargets = findingTargets(pen, penScene).items;
    expect(penTargets[0]).toBe(`penetration:${pen.key}`);
    expect(penTargets).toContain(`pipe:${pen.ids[0]}`);
    expect(kindsOf(pen, penScene)).toEqual(["penetration", "pipe", "structure"]);
    // A nozzle id names its nozzle.
    const open = findings.find((f) => f.rule === "cheme.layout-nozzle-unconnected")!;
    expect(findingTargets(open, scene).items).toEqual([`nozzle:${open.ids[0]}`]);
    // A part id (a rack beam) names its rack.
    const beam = model.racks[0]!.parts[0]!;
    const steel = { ...open, rule: "cheme.layout-clash-pipe-steel", ids: [beam.id] } as Finding;
    expect(findingTargets(steel, scene).items.some((k) => k.startsWith("rack:"))).toBe(true);
  });

  it("shows equipment details from the model and links its sheet and nozzles", () => {
    const k = scene.items.get("equipment:K-1101")!;
    expect(k.type).toBe("CentrifugalCompressor");
    expect(k.service).toBe("Main air compressor (MAC)");
    expect(Object.fromEntries(k.details)).toMatchObject({ family: "compressor", "mounted on": "building B1, level L0", nozzles: "8" });
    expect(k.related?.map((r) => r.label)).toEqual(expect.arrayContaining(["N1 DN 1400", "motor removal"]));
    expect(k.highlight).toBe("K1101");
    // the LOX tank stands on a 0.5 m concrete plinth (a part of its own)
    const tank = scene.items.get("equipment:T-4101")!;
    expect(Object.fromEntries(tank.details)).toMatchObject({ "on a plinth": "0.5 m" });
    const nozzle = scene.items.get("nozzle:F-1101/N1")!;
    expect(nozzle.line).toBe("AIR-1001");
    // core writes the sheet repo-relative
    expect(nozzle.sheetFile).toBe("pid/P-01.xml");
    expect(nozzle.highlight).toBe("F1101_N1");
  });

  it("resolves links by item key, tag, DEXPI id and nozzle id", () => {
    expect(resolveSelect("equipment:C-1101", scene)).toBe("equipment:C-1101");
    expect(resolveSelect("C-1101", scene)).toBe("equipment:C-1101");
    expect(resolveSelect("C1101", scene)).toBe("equipment:C-1101");
    expect(resolveSelect("F1101_N1", scene)).toBe("nozzle:F-1101/N1");
    expect(resolveSelect("PR1", scene)).toBe("rack:PR1");
    expect(resolveSelect("nothing", scene)).toBeNull();
    expect(resolveSelect(null, scene)).toBeNull();
  });

  it("keeps item bounds for focus at the model's bbox and what stands out of it", () => {
    const eq = model.equipment.find((e) => e.tag === "P-1101A")!;
    const box = scene.itemBounds.get("equipment:P-1101A")!;
    close(box.min, eq.bbox.slice(0, 3), 3);
    close(box.max, eq.bbox.slice(3), 3);
    // A column's top davit stands above its bbox: the bounds reach its top, the rest is the bbox.
    const column = model.equipment.find((e) => e.tag === "C-1101")!;
    const cb = scene.itemBounds.get("equipment:C-1101")!;
    const post = column.parts.find((p) => p.id === "C-1101/davit-post")!;
    close(cb.min, column.bbox.slice(0, 3), 3);
    expect(cb.max[2]).toBeCloseTo(post.end![2], 3);
    expect(cb.max[2]).toBeGreaterThan(column.bbox[5]!);
  });

  it("walks on the building levels, the frame's gratings and the platforms", () => {
    expect(scene.floors.map((f) => f.id)).toEqual(expect.arrayContaining(["B1/L0", "B1/RF", "CB-1/P10/grating", "C-1101/platform-1/grating"]));
    expect(floorsAt(scene.floors, 45, 30)).toEqual([0, 12.3]);
    const deck = model.structures[0]!.parts.find((p) => p.id === "CB-1/P10/grating")!;
    expect(floorsAt(scene.floors, deck.centre![0], deck.centre![1])).toContain(10);
  });
});

describe("parts", () => {
  it("turns each part kind into a primitive and refuses incomplete ones", () => {
    const base = { id: "x", refs: {}, source: "generated", material: "shell" };
    expect(partPrim({ ...base, kind: "member", start: [0, 0, 0], end: [0, 0, 3], profile: [0.3, 0.5], section: "HEB500" })).toEqual({ kind: "beam", start: [0, 0, 0], end: [0, 0, 3], width: 0.3, depth: 0.5 });
    expect(partPrim({ ...base, kind: "annulus", centre: [0, 0, 5], radius: 1, radius_end: 2, depth: 0.03 })).toEqual({ kind: "annulus", centre: [0, 0, 5], inner: 1, outer: 2, depth: 0.03, arc: null });
    expect(partPrim({ ...base, kind: "cone", start: [0, 0, 0], end: [0, 0, 2], radius: 1, radius_end: 0.2 })).toEqual({ kind: "cylinder", start: [0, 0, 0], end: [0, 0, 2], radius: 1, radiusEnd: 0.2 });
    expect(partPrim({ ...base, kind: "cap", centre: [0, 0, 5], axis: [0, 0, 2], radius: 1, depth: 0.5 })).toEqual({ kind: "cap", centre: [0, 0, 5], axis: [0, 0, 1], radius: 1, depth: 0.5 });
    expect(partPrim({ ...base, kind: "box", centre: [1, 2, 3], size: [2, 2, 2], rotation_deg: 90 })).toMatchObject({ kind: "box", rotationZ: Math.PI / 2 });
    expect(partPrim({ ...base, kind: "sphere", centre: [0, 0, 1], radius: 2 })).toMatchObject({ kind: "ellipsoid", radii: [2, 2, 2] });
    expect(partPrim({ ...base, kind: "cylinder", start: [0, 0, 0], radius: 1 })).toBeNull();
    expect(partPrim({ ...base, kind: "torus" })).toBeNull();
  });

  it("bounds primitives", () => {
    expect(primBounds({ kind: "cylinder", start: [0, 0, 0], end: [0, 0, 4], radius: 1, radiusEnd: 1 })).toEqual({ min: [-1, -1, 0], max: [1, 1, 4] });
    const turned = primBounds({ kind: "box", centre: [0, 0, 0], size: [4, 2, 2], rotationZ: Math.PI / 2 });
    close(turned.min, [-1, -2, -1]);
    expect(boxEdges([0, 0, 0], [1, 1, 1])).toHaveLength(12);
  });
});

// Small hand-made pipes, in-line items and zones for the geometry rules.
const later: LayoutModel = {
  ...model,
  equipment: [],
  structures: [],
  platforms: [],
  pipes: [
    {
      id: "AIR-1001/S1",
      refs: { lines: ["AIR-1001"], segments: ["Line_AIR1001_S1"], sheet: "pid/P-01.xml" },
      source: "generated",
      line: "AIR-1001",
      segment: "Line_AIR1001_S1",
      points: [
        [0, 0, 3],
        [10, 0, 3],
        [10, 10, 3],
        [10, 10, 8],
      ],
      segment_number: "S1",
      dn: 200,
      od: 0.2191,
      class: { code: "A1", material: "CS" },
      insulation_mm: 50,
      fluid: "air",
      length: 25,
      method: "rack",
      racks: ["PR1"],
      tier: 8,
    },
    { id: "CW-2001/S1", refs: { lines: ["CW-2001"], segments: ["Line_CW2001_S1"], sheet: "pid/P-02.xml" }, source: "pinned", line: "CW-2001", segment: "Line_CW2001_S1", points: [[0, 5, 1], [20, 5, 1]], dn: 100, od: 0.1143, insulation_mm: 0, class: { code: "B2", colour: "#123456" }, length: 20, method: "pinned" },
    { id: "WN-1/S1", refs: { lines: ["WN-1"], segments: ["S"], sheet: "pid/P-02.xml" }, source: "generated", line: "WN-1", segment: "S", points: [[0, 9, 1], [5, 9, 1]], dn: 50, od: 0.0603, insulation_mm: 0, length: 5, method: "direct", open_ends: ["end"], review_needed: true },
  ],
  inline: [
    { id: "P-01/Valve1", refs: { dexpi: "Valve1", tag: "HV-1" }, source: "generated", kind: "valve", dexpi_class: "GlobeValve", tag: "HV-1", point: [5, 0, 3], direction: [1, 0, 0], line: "AIR-1001", segment: "Line_AIR1001_S1", pipe: "AIR-1001/S1" },
    { id: "P-01/Meter1", refs: {}, source: "generated", kind: "instrument", dexpi_class: "FlowMeasuringElement", tag: "PI-1", point: [10, 5, 3], direction: [0, 1, 0], line: "AIR-1001", segment: "Line_AIR1001_S1", pipe: "AIR-1001/S1" },
    { id: "P-01/PSV1", refs: {}, source: "generated", kind: "safety_valve", dexpi_class: "SpringLoadedGlobeSafetyValve", point: [10, 10, 6], direction: [0, 0, 1], line: "AIR-1001", segment: "Line_AIR1001_S1", pipe: "AIR-1001/S1" },
    { id: "P-01/Sil1", refs: {}, source: "generated", kind: "silencer", dexpi_class: "Silencer", point: [10, 10, 7.5], direction: [0, 0, 1], line: "AIR-1001", segment: "Line_AIR1001_S1", pipe: "AIR-1001/S1" },
  ],
  zones: [
    { id: "Z1", refs: {}, source: "declared", kind: "oxygen_enriched", volumes: [{ shape: "cylinder", source: "declared", centre: [50, 50, 0], radius: 5, height: 3 }] },
    { id: "Z2", refs: {}, source: "generated", kind: "keep_clear", volumes: [{ shape: "box", source: "declared", box: [0, 0, 0, 4, 4, 2.5] }] },
    { id: "Z3", refs: {}, source: "generated", kind: "hazardous", zone: 2, volumes: [{ shape: "sphere", source: "generated", centre: [0, 0, 5], radius: 2 }] },
    { id: "Z4", refs: {}, source: "generated", kind: "laydown", volumes: [] },
  ],
  unrouted: [{ line: "N2-3001", segment: "Line_N23001_S1", sheet: "pid/P-03.xml", reason: "no route around C-3101" }],
};

describe("pipes, in-line items, structures and zones", () => {
  const s = buildModelScene(later, { sheets });

  it("runs pipes as straight pieces and elbows, with an insulation sleeve", () => {
    const air = s.meshes.filter((m) => m.item === "pipe:AIR-1001/S1");
    const pipes = air.filter((m) => m.layer === "pipes");
    const sleeves = air.filter((m) => m.layer === "insulation");
    expect(pipes.map((m) => m.prim.kind)).toEqual(["cylinder", "cylinder", "cylinder", "elbow", "elbow"]);
    expect(sleeves).toHaveLength(pipes.length);
    const r = odOf(200) / 2;
    const pipe = pipes[0]!.prim;
    const sleeve = sleeves[0]!.prim;
    if (pipe.kind === "cylinder" && sleeve.kind === "cylinder") {
      expect(pipe.radius).toBeCloseTo(r, 9);
      expect(sleeve.radius).toBeCloseTo(r + 0.05, 9);
    }
    expect(sleeves[0]!.opacity).toBeLessThan(1);
    expect(sleeves[0]!.color).toBe(lighten(pipes[0]!.color, 0.6));
    // Bare pipe: no sleeve.
    expect(s.meshes.filter((m) => m.item === "pipe:CW-2001/S1" && m.layer === "insulation")).toEqual([]);
    // A fallback route is flagged.
    expect(Object.fromEntries(s.items.get("pipe:WN-1/S1")!.details)).toMatchObject({ routed: "direct", "open end": "end", status: "review needed (fallback route)" });
  });

  it("colours pipes by service, or by class", () => {
    const air = s.meshes.find((m) => m.key === "pipe:AIR-1001/S1:s0")!;
    const cw = s.meshes.find((m) => m.key === "pipe:CW-2001/S1:s0")!;
    expect(air.color).toBe(serviceColor("air"));
    expect(cw.color).toBe(serviceColor("CW"));
    expect(cw.color).not.toBe(air.color);
    expect(air.classColor).not.toBe(cw.classColor);
    // The class's own colour from the pipe specs.
    expect(cw.classColor).toBe("#123456");
    expect(pipeService({ id: "x", line: "GOX-1001" })).toBe("GOX");
    expect(serviceColor("GOX")).toBe(serviceColor("LOX"));
  });

  it("shows a pipe's line, DN, OD, class, insulation, segment, fluid and length, and links the P&ID", () => {
    const item = s.items.get("pipe:AIR-1001/S1")!;
    expect(Object.fromEntries(item.details)).toMatchObject({
      line: "AIR-1001",
      segment: "Line_AIR1001_S1 (S1)",
      DN: "200",
      OD: "219.1 mm",
      class: "A1, CS",
      insulation: "50 mm",
      fluid: "air",
      length: "25 m",
      bends: "2",
      routed: "rack over PR1 at 8 m",
    });
    expect(item.sheetFile).toBe("pid/P-01.xml");
    expect(item.highlight).toBe("Line_AIR1001_S1");
    expect(s.ids.get("AIR-1001")).toBe("pipe:AIR-1001/S1");
    expect(s.ids.get("Line_AIR1001_S1")).toBe("pipe:AIR-1001/S1");
    expect(s.labels.find((l) => l.item === "pipe:AIR-1001/S1")?.text).toBe("AIR-1001");
  });

  it("draws a valve as two cones with a handwheel and an instrument as a bulb on a stem", () => {
    const valve = s.meshes.filter((m) => m.item === "inline:P-01/Valve1");
    expect(valve).toHaveLength(4);
    const [a, b] = valve;
    if (a?.prim.kind === "cylinder" && b?.prim.kind === "cylinder") {
      // tip to tip at the valve's point
      expect(a.prim.end).toEqual([5, 0, 3]);
      expect(b.prim.end).toEqual([5, 0, 3]);
      expect(a.prim.radiusEnd).toBeLessThan(a.prim.radius);
    }
    const instrument = s.meshes.filter((m) => m.item === "inline:P-01/Meter1").map((m) => m.prim.kind);
    expect(instrument).toEqual(["cylinder", "ellipsoid"]);
    // A safety valve has a bonnet instead of a handwheel; a silencer is a drum.
    expect(s.meshes.filter((m) => m.item === "inline:P-01/PSV1").map((m) => m.key)).toEqual(["inline:P-01/PSV1", "inline:P-01/PSV1:b", "inline:P-01/PSV1:bonnet"]);
    expect(s.meshes.filter((m) => m.item === "inline:P-01/Sil1")).toHaveLength(1);
    expect(s.ids.get("Valve1")).toBe("inline:P-01/Valve1");
    expect(s.ids.get("HV-1")).toBe("inline:P-01/Valve1");
    const valveItem = s.items.get("inline:P-01/Valve1")!;
    expect(valveItem).toMatchObject({ id: "HV-1", title: "GlobeValve", type: "valve", line: "AIR-1001" });
    expect(valveItem.related).toEqual([{ key: "pipe:AIR-1001/S1", label: "AIR-1001" }]);
  });

  it("draws zones as translucent volumes coloured by kind, and skips zones without a volume", () => {
    const zones = s.meshes.filter((m) => m.layer === "zones");
    expect(zones.map((m) => m.prim.kind)).toEqual(["cylinder", "box", "ellipsoid"]);
    expect(zones.every((m) => m.opacity < 0.3)).toBe(true);
    expect(new Set(zones.map((m) => m.color)).size).toBe(3);
    expect(s.items.get("zone:Z3")?.type).toBe("hazardous (zone 2)");
    expect(s.items.has("zone:Z4")).toBe(false);
  });

  it("puts the later sections into the full scene with legends", () => {
    const full = buildScene({ ...asu, model: later }, { sheets });
    // Services grouped by family, each row listing the services it stands for.
    expect(full.legend.pipes.map((e) => e.label)).toEqual(["air", "water", "nitrogen"]);
    expect(full.legend.pipes.map((e) => e.members)).toEqual([undefined, ["CW"], ["WN"]]);
    expect(full.legend.pipeClasses.map((e) => e.label)).toEqual(["A1", "B2", "no class"]);
    expect(full.legend.zones.map((e) => e.label)).toEqual(["oxygen enriched", "keep clear", "hazardous", "laydown"]);
    // Line numbers have a toggle of their own (off at first), below equipment tags in priority.
    const lineLabel = full.labels.find((l) => l.text === "AIR-1001")!;
    expect(lineLabel.toggle).toBe("lines");
    expect(lineLabel.priority).toBeLessThan(full.labels.find((l) => l.text === "K-1101")!.priority);
    expect(full.meshes.find((m) => m.key === "pipe:CW-2001/S1:s0")?.source).toBe("pinned");
    // A pipe links the nozzles its segment ends at.
    const withEquipment = buildModelScene({ ...later, equipment: model.equipment }, { sheets });
    expect(withEquipment.items.get("pipe:AIR-1001/S1")?.related).toContainEqual({ key: "nozzle:F-1101/N1", label: "F-1101/N1" });
  });
});

// Steel, platforms and zones the way core's structures and zones steps write them: generic
// parts (members with a profile, boxes, ring sectors) and zone volumes.
const steel: LayoutModel = {
  ...model,
  equipment: model.equipment.filter((e) => e.tag === "C-1101"),
  racks: [{ ...model.racks[0]!, parts: [{ id: "PR1/bent-0/col-a", refs: {}, source: "generated", kind: "member", material: "steel", start: [30, 65, 0], end: [30, 65, 8], profile: [0.3, 0.3], section: "HEB300" }] }],
  buildings: [{ ...model.buildings[0]!, walls: "all", parts: [{ id: "B1/wall-south-0", refs: {}, source: "generated", kind: "box", material: "cladding", centre: [40, 22.1, 6], size: [8, 0.2, 12], rotation_deg: 0 }] }],
  structures: [
    {
      id: "CB1",
      refs: { file: "layout/structures.yaml" },
      source: "declared",
      title: "Cold box",
      origin: [100, 100],
      rotation_deg: 0,
      width: 6,
      depth: 6,
      footprint: [100, 100, 106, 106],
      height: 30,
      grid_x: [0, 6],
      grid_y: [0, 6],
      levels: [{ id: "L1", elevation: 10, kind: "deck" }],
      sections: { column: "HEB300", beam: "HEB300", brace: "L100x10", assumed: true },
      parts: [
        { id: "CB1/col-0-0", refs: {}, source: "generated", kind: "member", material: "steel", start: [100, 100, 0], end: [100, 100, 10], profile: [0.3, 0.3], section: "HEB300" },
        { id: "CB1/L1/grating", refs: {}, source: "generated", kind: "box", material: "grating", centre: [103, 103, 9.985], size: [6, 6, 0.03], rotation_deg: 0 },
        { id: "CB1/L1/handrail-0", refs: {}, source: "generated", kind: "member", material: "handrail", start: [100, 100, 11.1], end: [106, 100, 11.1], profile: [0.05, 0.05], section: "RHS50x50" },
      ],
      stairs: [
        {
          id: "CB1/ST1",
          refs: { file: "layout/structures.yaml" },
          source: "declared",
          from: "grade",
          to: "L1",
          side: "south",
          width: 0.9,
          flights: 3,
          box: [100, 98, 0, 108, 100, 11.1],
          parts: [
            { id: "CB1/ST1/flight-0/stringer-a", refs: {}, source: "generated", kind: "member", material: "steel", start: [100.9, 99.95, 0], end: [104, 99.95, 3.3], profile: [0.075, 0.2] },
            { id: "CB1/ST1/flight-0/tread-1", refs: {}, source: "generated", kind: "box", material: "grating", centre: [101.2, 99.5, 0.18], size: [0.2, 0.9, 0.03], rotation_deg: 0 },
          ],
        },
      ],
      ladders: [
        {
          id: "CB1/LD1",
          refs: {},
          source: "declared",
          base: [106, 103, 0],
          top: [106, 103, 10],
          cage: true,
          parts: [
            { id: "CB1/LD1/rail-0", refs: {}, source: "generated", kind: "member", material: "steel", start: [106, 102.8, 0], end: [106, 102.8, 11.1], profile: [0.012, 0.07] },
            { id: "CB1/LD1/cage", refs: {}, source: "generated", kind: "cylinder", material: "cage", start: [106.35, 103, 2.3], end: [106.35, 103, 11.1], radius: 0.35 },
          ],
        },
      ],
      walls: [{ id: "CB1/wall-south", refs: {}, source: "generated", kind: "box", material: "casing", centre: [103, 99.9, 15], size: [6.4, 0.2, 30], rotation_deg: 0 }],
    },
  ],
  platforms: [
    {
      id: "C-1101/platform-1",
      refs: { tag: "C-1101" },
      source: "generated",
      tag: "C-1101",
      kind: "circular",
      elevation: 12,
      item_elevation: 12,
      width: 1,
      arc_deg: [300, 60],
      review_needed: true,
      parts: [
        { id: "C-1101/platform-1/grating", refs: {}, source: "generated", kind: "annulus", material: "grating", centre: [35, 72, 12], radius: 1.6, radius_end: 2.6, depth: 0.03, arc_deg: [300, 60] },
        { id: "C-1101/platform-1/handrail", refs: {}, source: "generated", kind: "annulus", material: "handrail", centre: [35, 72, 13.1], radius: 2.55, radius_end: 2.6, depth: 0.05, arc_deg: [300, 60] },
      ],
      ladder: { id: "C-1101/platform-1/ladder", refs: { tag: "C-1101" }, source: "generated", base: [37.85, 72, 0], top: [37.85, 72, 12], cage: true, parts: [{ id: "C-1101/platform-1/ladder/rail-0", refs: {}, source: "generated", kind: "member", material: "steel", start: [37.85, 71.8, 0], end: [37.85, 71.8, 13.1], profile: [0.012, 0.07] }] },
    },
  ],
  zones: [
    {
      id: "VENT-O2",
      refs: { file: "layout/zones.yaml" },
      source: "declared",
      title: "Oxygen vent",
      kind: "oxygen_enriched",
      volumes: [
        { shape: "cylinder", source: "generated", centre: [150, 40, 0], radius: 15, height: 23, item: "V-3101/N9", source_kind: "vent", release_grade: "primary", substance_class: "oxygen", basis: "ASSUMED radius table", status: "ASSUMED" },
        { shape: "sphere", source: "generated", centre: [150, 40, 8], radius: 15, item: "V-3101/N9" },
      ],
    },
  ],
};

describe("steel, platforms and zones from core's parts and volumes", () => {
  const s = buildModelScene(steel, { sheets });
  const full = buildScene({ ...asu, model: steel }, { sheets });

  it("draws a frame's parts by material: steel on the structures layer, gratings and rails on the platforms layer", () => {
    const cb = s.meshes.filter((m) => m.item === "structure:CB1");
    expect(cb.find((m) => m.key === "CB1/col-0-0")).toMatchObject({ layer: "structures", material: "steel", prim: { kind: "beam", width: 0.3, depth: 0.3 } });
    expect(cb.find((m) => m.key === "CB1/L1/grating")).toMatchObject({ layer: "platforms", material: "grating" });
    expect(cb.find((m) => m.key === "CB1/L1/grating")!.opacity).toBeLessThan(1);
    expect(cb.find((m) => m.key === "CB1/L1/handrail-0")?.layer).toBe("platforms");
    // Stair, ladder (with its cage) and the enclosure wall.
    expect(cb.filter((m) => m.key.startsWith("CB1/ST1/"))).toHaveLength(2);
    expect(cb.find((m) => m.key === "CB1/LD1/cage")).toMatchObject({ layer: "platforms", prim: { kind: "cylinder" } });
    expect(cb.find((m) => m.key === "CB1/wall-south")).toMatchObject({ layer: "structures", material: "casing" });
    const details = Object.fromEntries(s.items.get("structure:CB1")!.details);
    expect(details).toMatchObject({ size: "6 x 6 x 30 m", parts: "3", stairs: "grade to L1 (3 flights, south)", ladders: "1 (caged)", walls: "1", levels: "L1 @ 10 m", sections: "column HEB300, beam HEB300, brace L100x10 (ASSUMED)" });
  });

  it("walks on every grating: the deck, the stair treads and the platform ring", () => {
    expect(floorsAt(s.floors, 103, 103)).toEqual([0, 10]);
    expect(snapFloor(s.floors, 101.2, 99.5, 0)).toBeCloseTo(0.195, 6);
    expect(floorsAt(s.floors, 37.4, 72)).toContain(12);
  });

  it("draws a platform around a vessel as ring sectors with its ladder, as a proposal to review", () => {
    const ring = s.meshes.filter((m) => m.item === "platform:C-1101/platform-1");
    expect(ring.map((m) => m.prim.kind)).toEqual(["annulus", "annulus", "beam"]);
    expect(ring[0]!.prim).toEqual({ kind: "annulus", centre: [35, 72, 12], inner: 1.6, outer: 2.6, depth: 0.03, arc: [300, 60] });
    expect(ring.every((m) => m.layer === "platforms")).toBe(true);
    const item = s.items.get("platform:C-1101/platform-1")!;
    expect(Object.fromEntries(item.details)).toMatchObject({ floor: "12 m", arc: "300 to 60 deg", ladder: "caged", status: "proposed, review needed" });
    expect(item.related).toEqual([{ key: "equipment:C-1101", label: "C-1101" }]);
    expect(full.items.get("platform:C-1101/platform-1")?.source).toBe("generated");
  });

  it("uses core's rack bents and wall panels instead of drawing its own", () => {
    expect(s.meshes.find((m) => m.key === "PR1/bent-0/col-a")).toMatchObject({ item: "rack:PR1", layer: "structures" });
    expect(full.lines.find((l) => l.key === "rack:PR1")).toBeUndefined();
    expect(full.meshes.some((m) => m.key.startsWith("rack:PR1:m"))).toBe(false);
    // With a model, no rack is drawn from its centreline.
    expect(full.lines.find((l) => l.key === "rack:PR2")).toBeUndefined();
    const walls = s.meshes.filter((m) => m.item === "building:B1");
    expect(walls.map((m) => m.key)).toEqual(["B1/wall-south-0"]);
    expect(walls[0]).toMatchObject({ material: "cladding", layer: "buildings" });
  });

  it("draws every volume of a zone, with its sources and basis", () => {
    const zone = s.meshes.filter((m) => m.item === "zone:VENT-O2");
    expect(zone.map((m) => m.prim.kind)).toEqual(["cylinder", "ellipsoid"]);
    expect(new Set(zone.map((m) => m.color))).toEqual(new Set([zoneColor("oxygen_enriched")]));
    const details = Object.fromEntries(s.items.get("zone:VENT-O2")!.details);
    expect(details).toMatchObject({ shape: "cylinder, sphere", volumes: "2", sources: "V-3101/N9", basis: "ASSUMED radius table" });
    expect(volumePrim({ shape: "cylinder", source: "generated", centre: [0, 0, 0], radius: 2 })).toMatchObject({ end: [0, 0, 2] });
    expect(volumePrim({ shape: "box", source: "declared" })).toBeNull();
  });
});

describe("pipe runs", () => {
  it("rounds each corner with a bend tangent to both legs", () => {
    const run = pipeRun(
      [
        [0, 0, 0],
        [10, 0, 0],
        [10, 10, 0],
      ],
      1,
    );
    expect(run.straights).toEqual([
      [[0, 0, 0], [9, 0, 0]],
      [[10, 1, 0], [10, 10, 0]],
    ]);
    expect(run.elbows).toEqual([{ start: [9, 0, 0], corner: [10, 0, 0], end: [10, 1, 0] }]);
  });

  it("drops repeated and straight-through points and shortens bends on short legs", () => {
    const run = pipeRun(
      [
        [0, 0, 0],
        [0, 0, 0],
        [5, 0, 0],
        [10, 0, 0],
        [10, 1, 0],
      ],
      2,
    );
    expect(run.elbows).toHaveLength(1);
    // The 1 m leg allows half of it.
    expect(run.elbows[0]!.end).toEqual([10, 0.5, 0]);
    expect(run.straights.map(([a, b]) => [a[0], b[0]])).toEqual([
      [0, 5],
      [5, 9.5],
      [10, 10],
    ]);
    expect(pipeRun([[1, 1, 1]], 1)).toEqual({ straights: [], elbows: [] });
    expect(polylineLength([[0, 0, 0], [3, 4, 0], [3, 4, 2]])).toBe(7);
  });

  it("knows ODs by DN", () => {
    expect(odOf(100)).toBe(0.1143);
    expect(odOf(110)).toBeCloseTo(0.112, 6);
    expect(odOf(null)).toBe(0.1);
  });
});

describe("section box, walking and measuring", () => {
  const box = { min: [0, 0, 0] as [number, number, number], max: [10, 20, 5] as [number, number, number] };

  it("keeps what is inside the six planes", () => {
    const planes = sectionPlanes(box);
    expect(planes).toHaveLength(6);
    expect(planes[1]).toEqual({ normal: [-1, 0, 0], constant: 10 });
    expect(insideSection(box, [5, 5, 5])).toBe(true);
    expect(insideSection(box, [10.01, 5, 1])).toBe(false);
    expect(insideSection(box, [5, 5, -0.1])).toBe(false);
  });

  it("maps slider fractions onto the bounds, never min above max", () => {
    expect(sectionFromFractions(box, { min: [0.5, 0, 0], max: [0.25, 1, 2] })).toEqual({ min: [2.5, 0, 0], max: [5, 20, 5] });
  });

  const floors: Floor[] = [
    { id: "B/L1", elevation: 4, polygon: [[0, 0], [10, 0], [10, 10], [0, 10]] },
    { id: "B/L2", elevation: 8, polygon: [[0, 0], [10, 0], [10, 10], [0, 10]] },
    { id: "S/D1", elevation: 6, polygon: [[20, 0], [30, 0], [30, 10], [20, 10]] },
  ];

  it("snaps a walker to the floor under the feet and steps between levels", () => {
    expect(EYE_HEIGHT).toBe(1.7);
    expect(floorsAt(floors, 5, 5)).toEqual([0, 4, 8]);
    expect(floorsAt(floors, 15, 5)).toEqual([0]);
    expect(snapFloor(floors, 5, 5, 0)).toBe(0);
    expect(snapFloor(floors, 5, 5, 4.2)).toBe(4);
    // Steps up onto a floor at most 0.5 m above the feet, not more.
    expect(snapFloor(floors, 5, 5, 3.6)).toBe(4);
    expect(snapFloor(floors, 5, 5, 3)).toBe(0);
    // Walking off a deck drops to the ground.
    expect(snapFloor(floors, 15, 5, 6)).toBe(0);
    expect(stepFloor(floors, 5, 5, 0, 1)).toBe(4);
    expect(stepFloor(floors, 5, 5, 4, 1)).toBe(8);
    expect(stepFloor(floors, 5, 5, 8, 1)).toBe(8);
    expect(stepFloor(floors, 5, 5, 8, -1)).toBe(4);
    expect(stepFloor(floors, 25, 5, 0, 1)).toBe(6);
  });

  it("measures distances with their components", () => {
    expect(measure([0, 0, 0], [3, 4, 12])).toEqual({ distance: 13, dx: 3, dy: 4, dz: 12, horizontal: 5 });
    expect(measure([1, 1, 1], [1, 1, 1]).distance).toBe(0);
  });
});

describe("findings and views", () => {
  it("marks every item a finding names and its 3D box", () => {
    const finding: Finding = { file: "layout/plant-model.yaml", level: "error", rule: "cheme.layout-clash-3d", message: "", line: null, ids: ["C-1101", "F1101_N1", "nope"], hint: "", box: [1, 2, 3, 0, 5, 6] };
    expect(findingTargets(finding, scene)).toEqual({ items: ["equipment:C-1101", "nozzle:F-1101/N1"], box: { min: [0, 2, 3], max: [1, 5, 6] } });
    // A sheet box (4 numbers) is not a 3D box.
    expect(findingTargets({ ...finding, box: [0, 0, 1, 1] }, scene).box).toBeNull();
  });

  it("looks at the plot from each side", () => {
    const bounds = { min: [0, 0, 0] as [number, number, number], max: [100, 50, 30] as [number, number, number] };
    const north = cameraPose("north", bounds);
    const east = cameraPose("east", bounds);
    expect(north.position[1]).toBeGreaterThan(50);
    expect(north.position[0]).toBe(50);
    expect(east.position[0]).toBeGreaterThan(100);
    expect(cameraPose("south", bounds).position[1]).toBeLessThan(0);
    expect(cameraPose("west", bounds).position[0]).toBeLessThan(0);
    // Every view looks at the middle of the box.
    expect(north.target).toEqual([50, 25, 15]);
  });
});

describe("the view state in the URL", () => {
  it("leaves defaults out and reads back what it wrote", () => {
    const state = parseLayoutQuery({});
    expect(layoutQuery(state)).toEqual(Object.fromEntries(Object.keys(layoutQuery(state)).map((k) => [k, undefined])));
    state.select = "pipe:AIR-1001/S1";
    state.shown = state.shown.filter((t) => t !== "zones");
    state.mode = "provenance";
    state.xray = true;
    state.section = { min: [0, 0, 0], max: [10, 20.123, 5] };
    state.cam = { position: [1, 2, 3], target: [4, 5, 6] };
    state.view = "north";
    const query = layoutQuery(state);
    expect(query).toMatchObject({ select: "pipe:AIR-1001/S1", mode: "provenance", xray: "1", section: "0,0,0,10,20.12,5", cam: "1,2,3,4,5,6", view: undefined });
    expect(query.layers?.split(",")).not.toContain("zones");
    const back = parseLayoutQuery(query);
    expect(back).toMatchObject({ select: "pipe:AIR-1001/S1", mode: "provenance", xray: true, cam: state.cam, section: { min: [0, 0, 0], max: [10, 20.12, 5] } });
    expect(back.shown).toEqual(state.shown);
  });

  it("keeps the 2D settings only on the 2D tab and ignores bad values", () => {
    const state = parseLayoutQuery({ tab: "2d", drawing: "section", axis: "y", at: "42", mode: "rainbow", layers: "pipes,bogus", section: "1,2" });
    expect(state).toMatchObject({ tab: "2d", plan: { kind: "section", axis: "y", at: 42 }, mode: "normal", shown: ["pipes"], section: null });
    expect(layoutQuery(state)).toMatchObject({ tab: "2d", drawing: "section", axis: "y", at: "42", layers: "pipes" });
    expect(parseLayoutQuery({ layers: "none" }).shown).toEqual([]);
    expect(layoutQuery({ ...state, tab: "3d" })).toMatchObject({ drawing: undefined, axis: undefined, at: undefined });
  });
});

describe("sheet paths", () => {
  it("takes core's repo-relative sheet refs, mapped through the repo's sheet list", () => {
    expect(repoSheet("pid/P-01.xml", sheets)).toBe("pid/P-01.xml");
    expect(repoSheet("P-01", sheets)).toBe("pid/P-01.xml");
    expect(repoSheet("P-04", sheets)).toBe("pid/P-04.xml");
    expect(repoSheet("pid/P-09.xml", sheets)).toBe("pid/P-09.xml");
    expect(repoSheet(null, sheets)).toBeNull();
    // The four ASU sheets.
    expect(sheets.map((s) => s.id)).toEqual(["P-01", "P-02", "P-03", "P-04"]);
    // Every sheet ref of the ASU model is repo-relative and on the repo's sheet list.
    const refs = [...model.equipment.map((e) => e.refs.sheet), ...model.pipes.map((p) => p.refs.sheet), ...model.inline.map((i) => i.refs.sheet), ...model.unrouted.map((u) => u.sheet)];
    expect(refs.filter((r) => r && !sheetFiles.includes(r))).toEqual([]);
    expect(model.pipes.every((p) => p.refs.sheet) && model.inline.every((i) => i.refs.sheet)).toBe(true);
    // Equipment without a sheet ref is placed from the placement file only (a silencer or PSV drawn as an item).
    for (const e of model.equipment.filter((x) => !x.refs.sheet)) expect(e.refs.file, e.id).toBe("layout/equipment-placement.yaml");
  });
});
