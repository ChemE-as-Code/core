import { expect, test } from "@playwright/test";
import { mockApi, simulationAsu, simulationFailed, simulationRun, simulationStale, streamsSimulation } from "./fixtures";

/**
 * The Simulation tab of the stream table: core's real `/api/simulation` of its
 * examples/process-simulation (a run recorded with the stand-in solver: current, stale, not
 * converged) and of the ASU (no run, excluded units), and the values the run filled.
 */
test.describe("simulation", () => {
  test("a converged run: simulator, case, inputs, units, and the values it filled", async ({ page }) => {
    await mockApi(page, { simulation: simulationRun, streams: streamsSimulation });
    await page.goto("/streams");
    // The stream table is the default; the values the run filled are marked.
    const s2 = page.locator('tr[data-stream="S2"]');
    await expect(s2.locator("[data-sim]")).toHaveCount(4);
    await expect(s2.locator('td[data-field="temperature"] [data-sim]')).toHaveAttribute("title", /Filled by the simulation run of \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC \(dwsim 9\.0\.5\.0, Peng-Robinson \(PR\)\)/);
    await expect(page.locator('tr[data-stream="W1"] td[data-field="duty"] [data-sim]')).toHaveCount(1);
    await expect(page.locator('tr[data-stream="S1"] [data-sim]')).toHaveCount(0);
    await expect(page.locator(".legend")).toContainText("filled by the simulation");

    await page.getByRole("tab", { name: "Simulation" }).click();
    await expect(page).toHaveURL(/tab=simulation/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Simulation process/simulation.yaml in the working tree");
    const panel = page.getByRole("region", { name: "Simulation" });
    await expect(panel.locator("[data-simulator]")).toContainText("dwsim 9.0.5.0");
    await expect(panel.locator("[data-simulator]").getByRole("link", { name: "process/simulation.yaml" })).toHaveAttribute("href", /\/file\/process\/simulation\.yaml/);
    await expect(panel.locator("[data-package]")).toHaveText("Peng-Robinson (PR)");
    await expect(panel.locator("[data-run-state]")).toHaveText("converged");
    await expect(panel.locator("[data-run-state]")).toHaveClass(/pass/);
    await expect(panel.locator("[data-stale-badge]")).toHaveCount(0);
    await expect(panel.locator("[data-run-at]")).toHaveText(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC$/);
    const commit = simulationRun.run!.inputs.commit;
    await expect(panel.locator("[data-inputs]")).toContainText(`commit ${commit.slice(0, 7)}`);
    await expect(panel.locator("[data-inputs]")).toContainText("with uncommitted changes to process/flowsheet.yaml");
    await expect(panel.locator("[data-inputs] a")).toHaveAttribute("href", new RegExp(`rev=${commit}`));
    await expect(panel.locator("[data-filled-count]")).toContainText("17 stream values hold the simulated value");
    await expect(panel.locator("[data-no-run], [data-stale], [data-failed]")).toHaveCount(0);

    const units = page.getByRole("table", { name: "Simulation units" });
    await expect(units.locator("tbody tr")).toHaveCount(3);
    const k1 = units.locator('tr[data-unit="K1"]');
    await expect(k1).toContainText("compressor");
    await expect(k1.locator(".status .badge").first()).toHaveText("simulated");
    await expect(k1.locator("[data-conv]")).toHaveText("converged");
    const efficiency = k1.locator('[data-spec="efficiency"]');
    await expect(efficiency).toContainText("efficiency 0.78");
    await expect(efficiency).toHaveClass(/assumed/);
    await expect(efficiency.locator(".prov")).toHaveText("A");
    await expect(efficiency).toContainText("typical single-stage centrifugal");
    await expect(k1.locator('[data-spec="outlet_pressure"] .prov')).toHaveText("G");
    await expect(k1.locator('[data-result="duty_kW"]')).toHaveText("duty 84.2 kW");
    await expect(units.locator('tr[data-unit="E1"] [data-spec="pressure_drop"]')).toContainText("20 kPa");
    await expect(units.locator('tr[data-unit="E1"] [data-result="duty_kW"]')).toContainText("-81");
  });

  test("a stale run: the warning names the changed files; the marks say stale", async ({ page }) => {
    await mockApi(page, { simulation: simulationStale, streams: streamsSimulation });
    await page.goto("/streams?tab=simulation");
    const panel = page.getByRole("region", { name: "Simulation" });
    await expect(panel.locator("[data-stale-badge]")).toHaveText("stale");
    const warning = panel.locator("[data-stale]");
    await expect(warning).toContainText("The recorded run is stale");
    await expect(warning).toContainText("cheme process simulate --fill");
    await expect(warning.locator("[data-changed-file]")).toHaveText(["process/simulation.yaml"]);
    await expect(warning.locator("[data-changed-file]")).toHaveAttribute("href", /\/file\/process\/simulation\.yaml/);
    await page.getByRole("tab", { name: "Streams" }).click();
    await expect(page).not.toHaveURL(/tab=/);
    const mark = page.locator('tr[data-stream="S3"] td[data-field="pressure"] [data-sim]');
    await expect(mark).toHaveClass(/stale/);
    await expect(mark).toHaveAttribute("title", /the run is stale/);
  });

  test("a run that did not converge: its messages, the unit that failed, nothing filled", async ({ page }) => {
    await mockApi(page, { simulation: simulationFailed, streams: streamsSimulation });
    await page.goto("/streams?tab=simulation");
    const panel = page.getByRole("region", { name: "Simulation" });
    await expect(panel.locator("[data-run-state]")).toHaveText("not converged");
    await expect(panel.locator("[data-run-state]")).toHaveClass(/fail/);
    await expect(panel.locator("[data-failed]")).toContainText("E1: not calculated");
    await expect(panel.locator("[data-failed]")).toContainText("No stream value was written");
    const units = page.getByRole("table", { name: "Simulation units" });
    await expect(units.locator('tr[data-unit="E1"] [data-conv]')).toHaveText("failed");
    await expect(units.locator('tr[data-unit="E1"] .notes')).toContainText("E1: not calculated");
    await expect(units.locator('tr[data-unit="K1"] [data-conv]')).toHaveText("unknown");
    const findings = page.getByRole("region", { name: "Simulation findings" });
    await expect(findings.locator('li[data-rule="cheme.process-sim-not-converged"]')).toBeVisible();
    await page.getByRole("tab", { name: "Streams" }).click();
    await expect(page.locator("tr[data-stream]").first()).toBeVisible();
    await expect(page.locator("[data-sim]")).toHaveCount(0);
  });

  test("the ASU: no run recorded, the hint, excluded units with their reason, nested specs", async ({ page }) => {
    await mockApi(page, { simulation: simulationAsu });
    await page.goto("/streams?tab=simulation");
    const panel = page.getByRole("region", { name: "Simulation" });
    await expect(panel.locator("[data-run-state]")).toHaveText("not run");
    await expect(panel.locator("[data-no-run]")).toContainText("No run recorded for case design");
    await expect(panel.locator("[data-no-run]")).toContainText("cheme process simulate --fill");
    await expect(panel.locator("[data-no-run]")).toContainText("process/simulation-run.json");
    await expect(panel.locator("[data-inputs]")).toHaveCount(0);
    await expect(panel.locator("[data-exclude]")).toContainText("PUR, E3101, KT3101, X3101, C1102");
    const units = page.getByRole("table", { name: "Simulation units" });
    await expect(units.locator("tbody tr")).toHaveCount(simulationAsu.units.length);
    const pur = units.locator('tr[data-unit="PUR"]');
    await expect(pur.locator(".status .badge")).toHaveText("excluded");
    await expect(pur.locator("[data-reason]")).toHaveText("exclude: in process/simulation.yaml");
    await expect(units.locator('tr[data-unit="V2101"] [data-reason]')).toHaveText("inside PUR, excluded in process/simulation.yaml");
    const c3101 = units.locator('tr[data-unit="C3101"]');
    await expect(c3101).toContainText("distillation column");
    await expect(c3101.locator('[data-spec="side_draws.lin.flow"]')).toContainText("470");
    await expect(c3101.locator('[data-spec="vapor_flow"] .prov')).toHaveText("G");
    await expect(c3101.locator("[data-conv]")).toHaveCount(0);
    await expect(page.getByRole("region", { name: "Simulation findings" }).locator("li")).toHaveCount(1);
  });

  test("phone width: the panel and the units table fit", async ({ page }) => {
    await mockApi(page, { simulation: simulationAsu });
    await page.setViewportSize({ width: 375, height: 740 });
    await page.goto("/streams?tab=simulation");
    await expect(page.getByRole("table", { name: "Simulation units" })).toBeVisible();
    const overflow = await page.locator("main").evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    const [scroll, width] = await page.locator("html").evaluate((el) => [el.scrollWidth, el.clientWidth]);
    expect(scroll).toBeLessThanOrEqual(width! + 1);
  });

  test("without process/simulation.yaml (or on an older server): no tab, a hint", async ({ page }) => {
    await mockApi(page);
    await page.goto("/streams");
    await expect(page.locator("tr[data-stream]").first()).toBeVisible();
    await expect(page.getByRole("tab")).toHaveCount(0);
    await expect(page.locator("[data-sim]")).toHaveCount(0);
    await page.goto("/streams?tab=simulation");
    await expect(page.locator("[data-sim-missing]")).toContainText("No simulation");
    await expect(page.locator("[data-sim-missing]")).toContainText("cheme process simulate --fill");
    await page.getByRole("tab", { name: "Streams" }).click();
    await expect(page.locator("tr[data-stream]").first()).toBeVisible();
  });

  test("home links the simulation when the repo has one", async ({ page }) => {
    await mockApi(page, { simulation: simulationRun, streams: streamsSimulation });
    await page.goto("/");
    await page.getByRole("link", { name: "Simulation: the recorded run" }).click();
    await expect(page).toHaveURL(/\/streams\?tab=simulation/);
    await expect(page.getByRole("region", { name: "Simulation" })).toBeVisible();
  });
});
