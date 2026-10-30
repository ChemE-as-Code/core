import { expect, test } from "@playwright/test";
import { layout, mockApi } from "./fixtures";

/** The layout route against the real ASU /api/layout (with its generated model). */
test.describe("layout", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page);
  });

  test("draws the model, toggles a layer and keeps it in the URL", async ({ page }) => {
    await page.goto("/layout");
    await expect(page.locator("canvas.layout-canvas")).toBeVisible();
    await expect(page.locator(".layout-label", { hasText: "K-1101" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "3D" })).toHaveAttribute("aria-selected", "true");

    await page.locator("summary", { hasText: "Layers" }).click();
    const equipment = page.locator('input[data-layer="equipment"]');
    await expect(equipment).toBeChecked();
    await equipment.uncheck();
    await expect(page).toHaveURL(/layers=[^&]*nozzles/);
    expect(new URL(page.url()).searchParams.get("layers")!.split(",")).not.toContain("equipment");
    // The tags of a hidden layer go with it.
    await expect(page.locator(".layout-label", { hasText: "K-1101" })).toBeHidden();
    await equipment.check();
    await expect(page).not.toHaveURL(/layers=/);
    await expect(page.locator(".layout-label", { hasText: "K-1101" })).toBeVisible();
  });

  test("picks from the side list and from a tag, with details and a P&ID link", async ({ page }) => {
    await page.goto("/layout");
    await page.locator('.chip[data-item="equipment:K-1101"]').click();
    const panel = page.getByRole("region", { name: "Selection" });
    await expect(panel.locator(".tag")).toHaveText("K-1101");
    await expect(panel).toContainText("CentrifugalCompressor");
    await expect(panel).toContainText("compressor");
    await expect(page).toHaveURL(/select=equipment(%3A|:)K-1101/);

    await page.locator(".layout-label", { hasText: "F-1101" }).click();
    await expect(panel.locator(".tag")).toHaveText("F-1101");
    // A nozzle from the related list.
    await panel.getByRole("button", { name: "N1 DN 1400" }).click();
    await expect(panel.locator(".tag")).toHaveText("F-1101/N1");
    await expect(panel).toContainText("AIR-1001");

    await panel.locator('[data-action="open-pid"]').click();
    await expect(page).toHaveURL(/\/pid\/pid\/P-01\.xml\?select=F1101_N1/);
    // The P&ID offers the way back.
    await expect(page.locator('[data-action="show-3d"]')).toHaveAttribute("href", /\/layout\?select=F1101_N1/);
  });

  test("opens with a selection from a link", async ({ page }) => {
    await page.goto("/layout?select=C1101");
    const panel = page.getByRole("region", { name: "Selection" });
    await expect(panel.locator(".tag")).toHaveText("C-1101");
    await expect(page).toHaveURL(/select=equipment(%3A|:)C-1101/);
  });

  test("picks a merged mesh in the canvas by its vertex range", async ({ page }) => {
    // Focused on K-1101, with the building and the tags out of the way.
    await page.goto("/layout?select=K-1101&layers=site,areas,roads,structures,equipment,pipes");
    const panel = page.getByRole("region", { name: "Selection" });
    await expect(panel.locator(".tag")).toHaveText("K-1101");
    await panel.getByRole("button", { name: "Clear selection" }).click();
    await expect(panel).toHaveCount(0);
    const stage = page.locator(".layout .stage");
    const box = (await stage.boundingBox())!;
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await expect(panel.locator(".tag")).toHaveText("K-1101");
    await expect(page).toHaveURL(/select=equipment(%3A|:)K-1101/);
  });

  test("tags on, line numbers off and decluttered; the selection's labels always show", async ({ page }) => {
    await page.goto("/layout");
    await expect(page.locator("canvas.layout-canvas")).toBeVisible();
    await expect(page.locator(".layout-label", { hasText: "K-1101" })).toBeVisible();
    // No line numbers at first.
    const lineLabel = page.locator('.layout-label[data-item^="pipe:"]');
    expect(await lineLabel.evaluateAll((els) => els.filter((e) => (e as unknown as { style: { display: string } }).style.display !== "none").length)).toBe(0);
    // Shown tags do not overlap.
    const boxes = await page.locator(".layout-label").evaluateAll((els) =>
      els.filter((e) => (e as unknown as { style: { display: string } }).style.display !== "none").map((e) => e.getBoundingClientRect()).map((r) => [r.left, r.top, r.right, r.bottom]),
    );
    expect(boxes.length).toBeGreaterThan(5);
    for (let i = 0; i < boxes.length; i++)
      for (let j = i + 1; j < boxes.length; j++) {
        const [a, b] = [boxes[i]!, boxes[j]!];
        const overlap = Math.min(a[2]!, b[2]!) - Math.max(a[0]!, b[0]!) > 1 && Math.min(a[3]!, b[3]!) - Math.max(a[1]!, b[1]!) > 1;
        expect(overlap, `labels ${i} and ${j} overlap`).toBe(false);
      }
    // A selected pipe shows its line number although line numbers are off.
    await page.goto("/layout?select=P-01/Line_AIR1002_S1");
    await expect(page.locator('.layout-label[data-item="pipe:P-01/Line_AIR1002_S1"]')).toBeVisible();
    // The toggle brings them back, and goes into the URL.
    await page.goto("/layout");
    await page.locator("summary", { hasText: "Layers" }).click();
    const lines = page.locator('input[data-layer="lines"]');
    await expect(lines).not.toBeChecked();
    await lines.check();
    await expect(page).toHaveURL(/layers=[^&]*lines/);
    // Line numbers show up close: zoom in on the middle of the plant.
    const stage = (await page.locator(".layout .stage").boundingBox())!;
    await page.mouse.move(stage.x + stage.width / 2, stage.y + stage.height / 2);
    for (let i = 0; i < 6; i++) await page.mouse.wheel(0, -400);
    await expect.poll(() => lineLabel.evaluateAll((els) => els.filter((e) => (e as unknown as { style: { display: string } }).style.display !== "none").length)).toBeGreaterThan(0);
  });

  test("frames the plant, the site on request; the legend starts closed", async ({ page }) => {
    await page.goto("/layout");
    await expect(page.locator("canvas.layout-canvas")).toBeVisible();
    await page.getByRole("button", { name: "Top", exact: true }).click();
    await page.getByRole("button", { name: "Site", exact: true }).click();
    await expect(page).toHaveURL(/view=site/);
    await page.getByRole("button", { name: "Iso", exact: true }).click();
    await expect(page).toHaveURL(/view=iso/);

    const legend = page.getByRole("region", { name: "Legend" });
    const toggle = legend.getByRole("button", { name: "Legend" });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(legend).not.toContainText("Equipment");
    await toggle.click();
    await expect(legend.getByRole("region", { name: "Equipment" })).toContainText("heat exchangers");
    await expect(legend.getByRole("region", { name: "Services" })).toContainText("nitrogen");
  });

  test("keeps the legend off the scene on a narrow window", async ({ page }) => {
    await page.setViewportSize({ width: 600, height: 900 });
    await page.goto("/layout");
    await expect(page.locator("canvas.layout-canvas")).toBeVisible();
    await page.getByRole("button", { name: "Legend" }).click();
    const stage = (await page.locator(".layout .stage").boundingBox())!;
    const legend = (await page.locator(".legend").boundingBox())!;
    expect(legend.y).toBeGreaterThanOrEqual(stage.y + stage.height - 1);
  });

  test("shows the P&ID's selection in 3D", async ({ page }) => {
    await page.goto("/pid/pid/P-01.xml");
    await page.locator('.pid .pane [id="Pump1"] circle').click();
    const link = page.locator('[data-action="show-3d"]');
    await expect(link).toHaveAttribute("href", "/layout?select=Pump1");
  });

  test("display modes, section box, measure and export", async ({ page }) => {
    // Five scene rebuilds (mode, x-ray, section, walk, orbit) and a .glb export of the ASU model:
    // 22-31 s on CI runners without a GPU, at the default 30 s limit.
    test.setTimeout(60_000);
    await page.goto("/layout");
    await expect(page.locator("canvas.layout-canvas")).toBeVisible();
    await page.getByLabel("Colour by").selectOption("provenance");
    await expect(page).toHaveURL(/mode=provenance/);
    await page.getByRole("button", { name: "Legend" }).click();
    await expect(page.getByRole("region", { name: "Legend" })).toContainText("generated");
    await page.getByRole("button", { name: "X-ray" }).click();
    await expect(page).toHaveURL(/xray=1/);

    await page.getByRole("button", { name: "Section box" }).click();
    const zMax = page.getByLabel("z max, m");
    await expect(zMax).toBeVisible();
    await zMax.fill("6");
    await zMax.press("Enter");
    await expect(page).toHaveURL(/section=[-\d.]+,[-\d.]+,[-\d.]+,[-\d.]+,[-\d.]+,6(&|$)/);

    await page.getByRole("button", { name: "Measure" }).click();
    await expect(page.locator(".measure-help")).toContainText("Click two points");

    await page.getByRole("button", { name: "Walk" }).click();
    await expect(page.locator(".nav-help")).toContainText("1.7 m");
    await page.getByRole("button", { name: "Orbit" }).click();
    await expect(page.locator(".nav-help")).toBeHidden();

    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export .glb" }).click();
    const file = await download;
    expect(file.suggestedFilename()).toBe("layout-working-tree.glb");
    const path = await file.path();
    const { readFileSync } = await import("node:fs");
    const head = readFileSync(path).subarray(0, 4).toString("latin1");
    expect(head).toBe("glTF");

    await page.getByLabel("STL scale").selectOption("500");
    const stlDownload = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export .stl" }).click();
    const stl = await stlDownload;
    expect(stl.suggestedFilename()).toBe("layout-working-tree.1-500.stl");
    const bytes = readFileSync(await stl.path());
    const triangles = bytes.readUInt32LE(80);
    expect(triangles).toBeGreaterThan(1000);
    expect(bytes.length).toBe(84 + triangles * 50);
  });

  test("lists the model's findings and marks the objects they name", async ({ page }) => {
    await page.goto("/layout");
    await expect(page.locator("canvas.layout-canvas")).toBeVisible();
    // Many findings: grouped by rule with counts, the groups closed.
    await expect(page.locator('.finding-group[data-rule$="layout-line-length"] summary')).toContainText(/layout-line-length\s*16/);
    const group = page.locator('.finding-group[data-rule$="layout-nozzle-unconnected"]');
    await expect(group.locator("summary")).toContainText(/layout-nozzle-unconnected\s*2/);
    await expect(group).not.toHaveAttribute("open");
    const finding = group.locator(".finding", { hasText: "nozzle C-3101/N3 (GAN-3002) has no pipe" }).first();
    await expect(finding).toBeHidden();
    await group.locator("summary").click();
    await finding.click();
    await expect(finding).toHaveAttribute("aria-pressed", "true");
    const panel = page.getByRole("region", { name: "Selection" });
    await expect(panel.locator(".tag")).toHaveText("C-3101/N3");
    await expect(page).toHaveURL(/select=nozzle(%3A|:)C-3101(%2F|\/)N3/);
    // The finding's file is the model.
    await expect(finding.locator("xpath=..").locator("a.file")).toHaveText("layout/plant-model.yaml");
  });

  test("shows the routing summary, rack fill and what is not routed", async ({ page }) => {
    await page.goto("/layout");
    const routing = page.getByRole("region", { name: "Routing" });
    await expect(routing).toContainText("214 of 218 segments");
    await expect(routing).toContainText("astar");
    // Since process-library#4 more routes are pinned than the router found any other way.
    await expect(routing.locator("dl.methods dt").first()).toHaveText("pinned");
    await expect(routing.locator('tr[data-rack="PR1"]')).toHaveCount(3);
    await expect(routing.locator('tr[data-rack="PR2"]').first()).toContainText("6 %");
    // Nothing to review in the final ASU model.
    await expect(routing).not.toContainText("fallback pipe routes");
    // Why the router took each route, most first, and the battery limits.
    const reasons = routing.locator("details.reasons");
    await expect(reasons.locator("summary")).toHaveText("Why: 10 reasons");
    await reasons.locator("summary").click();
    await expect(reasons.locator("dt").first()).toHaveText("pinned");
    await expect(reasons.locator('dt[data-reason="rack: battery limit at a rack end"] + dd')).toHaveText("13");
    await expect(routing.getByLabel("Battery limits")).toHaveText("Battery limits: 13 by battery limit rule");
    await routing.getByRole("button", { name: "PR2" }).first().click();
    await expect(page.getByRole("region", { name: "Selection" }).locator(".tag")).toHaveText("PR2");

    const unrouted = page.getByRole("region", { name: "Unrouted" });
    await expect(unrouted.locator("li")).toHaveCount(4);
    await expect(unrouted).toContainText("internal of the double column");
    await expect(unrouted.locator('li[data-segment="Line_VNT3004_S2"] a')).toHaveText("VNT-3004 S2");
    await expect(unrouted.locator('li[data-segment="Line_VNT3004_S2"] a')).toHaveAttribute("href", /\/pid\/pid\/P-03\.xml\?select=Line_VNT3004_S2/);
  });

  test("shows a pipe's routing reason", async ({ page }) => {
    await page.goto("/layout?select=P-01/Line_AIR1001_S1");
    const panel = page.getByRole("region", { name: "Selection" });
    await expect(panel.locator(".tag")).toHaveText("P-01/Line_AIR1001_S1");
    await expect(panel).toContainText("local: pipe-way");
  });

  test("shows what to review in the provenance colours", async ({ page }) => {
    // The final ASU model has nothing to review: mark a fallback route and a proposed platform.
    const model = layout.model!;
    const review = {
      ...layout,
      model: {
        ...model,
        pipes: model.pipes.map((p) => (p.id === "P-01/Line_AIR1002_S1" ? { ...p, method: "direct", review_needed: true } : p)),
        platforms: model.platforms.map((p) => (p.id === "C-1101/platform-1" ? { ...p, source: "generated", review_needed: true } : p)),
      },
    };
    await page.route("**/api/layout?*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(review) }));
    await page.route("**/api/layout", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(review) }));
    await page.goto("/layout?select=P-01/Line_AIR1002_S1&mode=provenance");
    const panel = page.getByRole("region", { name: "Selection" });
    await expect(panel.locator(".tag")).toHaveText("P-01/Line_AIR1002_S1");
    await expect(panel.locator(".badge.review")).toHaveText("review needed");
    await expect(panel).toContainText("direct");
    await page.getByRole("button", { name: "Legend" }).click();
    await expect(page.locator(".legend")).toContainText("review needed");
    await page.goto("/layout?select=C-1101/platform-1");
    await expect(panel.locator(".tag")).toHaveText("C-1101/platform-1");
    await expect(panel.locator(".badge.review")).toBeVisible();
    await expect(panel.getByRole("button", { name: "C-1101", exact: true })).toBeEnabled();
  });

  test("draws a repository without a generated model from the placement", async ({ page }) => {
    await page.route("**/api/layout?*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...layout, model: null, zones: [], model_findings: [] }) }));
    await page.route("**/api/layout", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...layout, model: null, zones: [], model_findings: [] }) }));
    await page.route("**/api/layout/*.svg*", (route) => route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"no layout model"}' }));
    await page.goto("/layout");
    await expect(page.locator("canvas.layout-canvas")).toBeVisible();
    await expect(page.locator(".layout-label", { hasText: "K-1101" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Routing" })).toHaveCount(0);
    await expect(page.getByRole("tab", { name: "2D" })).toHaveCount(0);
  });

  test("the 2D tab shows core's plan and section drawings", async ({ page }) => {
    await page.goto("/layout");
    await page.getByRole("tab", { name: "2D" }).click();
    await expect(page).toHaveURL(/tab=2d/);
    const pane = page.locator(".drawing .pane");
    await expect(pane.locator("text", { hasText: "Plan plot" })).toBeAttached();
    await page.getByLabel("Level").selectOption("L0");
    await expect(pane.locator("text", { hasText: "Plan L0" })).toBeAttached();
    // The frame's platform levels are levels too.
    await page.getByLabel("Level").selectOption("P20");
    await expect(pane.locator("text", { hasText: "Plan P20" })).toBeAttached();
    // A cut range, and a bad one (core answers 400).
    await page.getByLabel("Level").selectOption({ label: "plot plan" });
    await page.getByLabel("z range").fill("0,6");
    await page.getByLabel("z range").press("Enter");
    await expect(pane.locator("text", { hasText: "Plan z=0,6" })).toBeAttached();
    await page.getByLabel("z range").fill("six");
    await page.getByLabel("z range").press("Enter");
    await expect(page.locator(".drawing [role=alert]")).toContainText("z must be a,b");
    await page.getByLabel("z range").fill("");
    await page.getByLabel("z range").press("Enter");
    await expect(pane.locator("text", { hasText: "Plan plot" })).toBeAttached();
    await page.getByRole("button", { name: "Section", exact: true }).click();
    await expect(pane.locator("text", { hasText: /Section x=\d+/ })).toBeAttached();
    await expect(page).toHaveURL(/drawing=section/);
    await page.getByRole("tab", { name: "3D" }).click();
    await expect(page.locator("canvas.layout-canvas")).toBeVisible();
  });

  test("another revision keeps the 2D tab while its layout loads", async ({ page }) => {
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route((url) => url.pathname === "/api/layout", async (route) => {
      if (new URL(route.request().url()).searchParams.get("rev") !== "v2") return route.fallback();
      await held;
      return route.fallback();
    });
    await page.goto("/layout");
    await page.getByRole("tab", { name: "2D" }).click();
    const pane = page.locator(".drawing .pane");
    await expect(pane.locator("text", { hasText: "Plan plot" })).toBeAttached();
    await page.locator('button[title^="Show another revision"]').click();
    await page.locator("#rev-select").fill("v2");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/rev=v2/);
    // The layout of v2 is loading: the old drawing is gone, the 2D tab stays.
    await expect(pane).toHaveCount(0);
    await expect(page).toHaveURL(/tab=2d/);
    release();
    await expect(page.locator(".drawing .pane text", { hasText: "Plan plot" })).toBeAttached();
    await expect(page).toHaveURL(/tab=2d/);
    await expect(page.getByRole("tab", { name: "2D" })).toHaveAttribute("aria-selected", "true");
  });

  test("hides the 2D tab when the server draws no plans", async ({ page }) => {
    await page.route("**/api/layout/*.svg*", (route) => route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"not found"}' }));
    await page.goto("/layout?tab=2d");
    await expect(page.locator("canvas.layout-canvas")).toBeVisible();
    await expect(page.getByRole("tab", { name: "2D" })).toHaveCount(0);
    await expect(page).not.toHaveURL(/tab=2d/);
  });
});
