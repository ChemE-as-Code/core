import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";
import maturityAsuJson from "../tests/fixtures/api/maturity-asu.json" with { type: "json" };

/**
 * The declared project phase beside the evidence-based maturity (core's `cheme maturity`, the
 * ASU's real report: no level reached), in the header, on the overview and on /maturity.
 */
type Report = Omit<typeof maturityAsuJson, "level"> & { level: string | null };

/** The ASU's report as if its sourced and balanced requirements passed (level `balanced`). */
function balanced(): Report {
  const report = structuredClone(maturityAsuJson) as Report;
  for (const level of report.levels.slice(0, 2)) {
    for (const r of level.requirements) if (r.required) r.status = "pass";
    level.status = "pass";
    level.reached = true;
  }
  report.level = "balanced";
  return report;
}

const DETAIL = { stage: "detail", stages: [{ id: "basic", title: "Basic engineering" }, { id: "detail", title: "Detailed engineering" }] };

test.describe("maturity", () => {
  test("a plant in detailed engineering shows its phase and, separately, the maturity the evidence supports", async ({ page }) => {
    await mockApi(page, { repo: DETAIL, maturity: balanced() });
    await page.goto("/");
    await expect(page.getByTestId("phase-badge")).toHaveText("Project phase: Detailed engineering");
    await expect(page.getByTestId("phase-badge")).toHaveAttribute("title", /not evidence/);
    await expect(page.getByTestId("maturity-badge")).toHaveText("Verified maturity: Balanced");
    await expect(page.getByTestId("home-maturity")).toHaveText("Balanced");

    await page.getByTestId("maturity-badge").click();
    await expect(page).toHaveURL(/\/maturity/);
    const levels = page.locator("ol.levels > li");
    await expect(levels).toHaveCount(4);
    await expect(levels.nth(0)).toHaveAttribute("data-state", "achieved");
    await expect(levels.nth(1).getByTestId("level-state")).toContainText("Achieved");
    await expect(levels.nth(2).getByTestId("level-state")).toContainText("Not yet achieved");
    await expect(levels.nth(3)).toContainText("not verified detailed engineering");
    await expect(levels.nth(3).getByTestId("level-state")).toContainText("Not yet achieved");
    await expect(levels.nth(2).locator('[data-requirement="predictive.run-record"]')).toContainText("missing");
    await expect(page.getByTestId("maturity-claim")).toContainText("basic-engineering");
    await expect(page.getByTestId("maturity-artifacts")).toContainText("never establishes calculation maturity");
    await expect(page.getByTestId("maturity-review")).toContainText("unreviewed");
  });

  test("no level reached reads Not established; another revision never shows the working tree's level", async ({ page }) => {
    const recorded = { ...balanced(), source: { commit: "b63c88d", dirty: [], fingerprints: { "process/flowsheet.yaml": "sha256:00" } } };
    await mockApi(page, { maturity: maturityAsuJson, files: { "checks/maturity.json": JSON.stringify(recorded) } });
    await page.goto("/maturity");
    await expect(page.getByTestId("maturity-badge")).toHaveText("Verified maturity: Not established");
    await expect(page.locator("ol.levels > li[data-state=achieved]")).toHaveCount(0);

    await page.goto("/maturity?rev=v0.1");
    await expect(page.getByTestId("maturity-badge")).toHaveText("Verified maturity: outdated report");
    await expect(page.getByTestId("maturity-stale")).toContainText("process/flowsheet.yaml");
    await expect(page.getByText("as recorded, not current")).toBeVisible();
    await expect(page.locator(".levels .badge.pass")).toHaveCount(0);
  });

  test("without any report the state is explicit and neutral, also on a phone", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 800 });
    await mockApi(page);
    await page.goto("/");
    await expect(page.getByTestId("home-maturity")).toHaveText("no report");
    await expect(page.getByTestId("maturity-badge")).toBeHidden();
    await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Maturity" }).click();
    await expect(page.getByTestId("maturity-missing")).toContainText("Nothing is shown as achieved");
  });
});
