import { expect, test, type Page } from "@playwright/test";
import { mockApi } from "./fixtures";

/**
 * The realistic look and the level of detail on the ASU fixture, and the frame rate at full
 * detail. `LAYOUT_SHOTS=<dir>` saves screenshots of both looks for checking by eye. The frame rate must
 * meet the budget of 30 fps at full detail; on CI (`CI` set: software rendering) it is only reported,
 * and `LAYOUT_FPS_MIN` sets it explicitly.
 */
const SHOTS = process.env.LAYOUT_SHOTS ?? "";
// CI runners render in software (well under 1 fps), so there the frame rate is only reported.
const FPS_MIN = Number(process.env.LAYOUT_FPS_MIN ?? (process.env.CI ? 0 : 30));

/** Two animation frames (the first compiles the shaders). */
const TWO_FRAMES = "new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))";

interface Stats {
  batches: number;
  instanced: number;
  instances: number;
  detail: number;
  detailShown: number;
  calls: number;
  triangles: number;
}

type Hook = {
  __layoutRenderer?: {
    stats(): Stats;
    benchmark(ms: number): Promise<{ fps: number; frames: number; calls: number; triangles: number }>;
    exportGlb(): Promise<ArrayBuffer>;
  };
};

async function ready(page: Page): Promise<void> {
  // Full detail of the ASU builds for several seconds on CI runners without a GPU.
  await expect(page.locator("canvas.layout-canvas")).toBeVisible({ timeout: 45_000 });
  await page.waitForFunction(() => !!(globalThis as unknown as Hook).__layoutRenderer, null, {
    timeout: 45_000,
  });
  await page.evaluate(TWO_FRAMES);
}

async function shot(page: Page, name: string): Promise<void> {
  if (!SHOTS) return;
  await page.waitForTimeout(300);
  await page.locator(".layout .stage").screenshot({ path: `${SHOTS}/${name}.png` });
}

// The GPU, not the software rasteriser headless Chromium falls back to (Metal on macOS), and no
// frame-rate cap, so the benchmark measures the renderer rather than the display.
test.use({ launchOptions: { args: ["--ignore-gpu-blocklist", "--enable-gpu", "--disable-gpu-vsync", "--disable-frame-rate-limit", ...(process.platform === "darwin" ? ["--use-angle=metal"] : [])] } });

test.describe("realistic look and detail", () => {
  test.describe.configure({ timeout: 120_000 });
  test.beforeEach(async ({ page }) => {
    await mockApi(page);
  });

  test("turns the realistic look and the detail on, kept in the URL", async ({ page }) => {
    await page.goto("/layout");
    await ready(page);
    await shot(page, "iso-normal");
    const realistic = page.getByRole("button", { name: "Realistic" });
    await expect(realistic).toHaveAttribute("aria-pressed", "false");
    await realistic.click();
    await expect(realistic).toHaveAttribute("aria-pressed", "true");
    await expect(page).toHaveURL(/look=realistic/);
    await shot(page, "iso-realistic");

    await page.getByLabel("Detail", { exact: true }).selectOption("full");
    await expect(page).toHaveURL(/detail=full/);
    const stats = await page.evaluate(() => (globalThis as unknown as Hook).__layoutRenderer!.stats());
    expect(stats.detailShown).toBe(stats.detail);
    await page.getByLabel("Detail", { exact: true }).selectOption("envelope");
    await page.evaluate(TWO_FRAMES);
    expect((await page.evaluate(() => (globalThis as unknown as Hook).__layoutRenderer!.stats())).detailShown).toBe(0);

    // Reloads as it was.
    await page.reload();
    await ready(page);
    await expect(page.getByRole("button", { name: "Realistic" })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByLabel("Detail", { exact: true })).toHaveValue("envelope");
  });

  test("close-ups of a pump and a frame in both looks", async ({ page }) => {
    test.skip(!SHOTS, "screenshots only on request");
    // Camera poses (position, target) over the ASU (buildings off): a pump pair, the main air
    // compressor, the cold box's stair, a column platform, the LOX tanks.
    const LAYERS = "site,areas,roads,structures,platforms,equipment,nozzles,pipes,insulation,inline,zones";
    for (const [name, cam] of [
      ["pump", "62.6,53.6,2.4,66,57,0.6"],
      ["compressor", "33,19,10,45,30,2"],
      ["stair", "152,33,9,142,41.5,5"],
      ["platform", "64,44,16,72,52,11"],
      ["tanks", "110,93,15,124,110,4"],
    ] as const) {
      for (const look of ["normal", "realistic"]) {
        await page.goto(`/layout?cam=${cam}&layers=${LAYERS}${look === "realistic" ? "&look=realistic" : ""}`);
        await ready(page);
        await shot(page, `${name}-${look}`);
      }
    }
  });

  test("the .glb at full detail needs no extension and keeps the instanced parts' colours", async ({ page }) => {
    await page.goto("/layout?detail=full");
    await ready(page);
    const glb = await page.evaluate(async () => {
      const data = await (globalThis as unknown as Hook).__layoutRenderer!.exportGlb();
      const view = new DataView(data);
      const length = view.getUint32(12, true);
      const json = JSON.parse(new TextDecoder().decode(new Uint8Array(data, 20, length)));
      type Node = { name?: string; mesh?: number; extensions?: Record<string, unknown> };
      type Mesh = { primitives: { attributes: Record<string, number>; material?: number }[] };
      const nodes: Node[] = json.nodes ?? [];
      const meshes: Mesh[] = json.meshes ?? [];
      const merged = nodes.filter((n) => n.name?.includes(":merged") && n.mesh !== undefined);
      return {
        used: json.extensionsUsed ?? [],
        required: json.extensionsRequired ?? [],
        instancedNodes: nodes.filter((n) => n.extensions?.EXT_mesh_gpu_instancing).length,
        merged: merged.length,
        mergedWithColour: merged.filter((n) => meshes[n.mesh!]!.primitives.every((p) => "COLOR_0" in p.attributes)).length,
      };
    });
    expect(glb.required).toEqual([]);
    expect(glb.used).not.toContain("EXT_mesh_gpu_instancing");
    expect(glb.instancedNodes).toBe(0);
    expect(glb.merged).toBeGreaterThan(0); // the instanced detail, baked into plain meshes
    expect(glb.mergedWithColour).toBe(glb.merged);
  });

  test("the test hook goes with the renderer when the layout is left", async ({ page }) => {
    await page.goto("/layout");
    await ready(page);
    await page.locator("[data-action=open-mto]").first().click();
    await expect(page).toHaveURL(/\/mto/);
    await expect(page.locator("canvas.layout-canvas")).toHaveCount(0);
    expect(await page.evaluate(() => "__layoutRenderer" in globalThis)).toBe(false);
  });

  test("frame rate at full detail on the ASU", async ({ page }, info) => {
    await page.goto("/layout?look=realistic&detail=full");
    await ready(page);
    const real = await page.evaluate(() => (globalThis as unknown as Hook).__layoutRenderer!.benchmark(3000));
    const stats = await page.evaluate(() => (globalThis as unknown as Hook).__layoutRenderer!.stats());
    await page.goto("/layout?detail=full");
    await ready(page);
    const normal = await page.evaluate(() => (globalThis as unknown as Hook).__layoutRenderer!.benchmark(3000));
    const report = { realistic: real, normal, batches: stats.batches, instanced: stats.instanced, instances: stats.instances, detail: stats.detail };
    console.log(`layout fps: ${JSON.stringify(report)}`);
    info.annotations.push({ type: "fps", description: JSON.stringify(report) });
    expect(real.frames).toBeGreaterThan(1);
    expect(real.fps).toBeGreaterThanOrEqual(FPS_MIN);
    expect(normal.fps).toBeGreaterThanOrEqual(FPS_MIN);
  });
});
