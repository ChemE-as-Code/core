import { expect, test } from "@playwright/test";
import { controlSeparation, mockApi } from "./fixtures";

/**
 * The control page: core's examples/process-separation (`/api/control`, pre-release issue 140): five loops,
 * two sequences, a narrative and a control philosophy, every file drafted (no review record).
 */
test.describe("control records", () => {
  test("files with their review status, the loop summary, the sequences and the findings", async ({ page }) => {
    await mockApi(page, { control: controlSeparation });
    await page.goto("/");
    await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Control", exact: true }).click();
    await expect(page).toHaveURL(/\/control/);

    const files = page.getByRole("region", { name: "Files" });
    await expect(files.locator('tr[data-file="control/loops.yaml"] [data-status]')).toHaveText("drafted");
    await expect(files.locator('tr[data-file="process/narrative.md"]')).toContainText("no review record covers it");

    const loops = page.getByRole("region", { name: "Loops" });
    await expect(loops.locator("tr[data-loop]")).toHaveCount(5);
    const fic = loops.locator('tr[data-loop="FIC-101"]');
    await expect(fic).toContainText("flow: FT-101");
    await expect(fic).toContainText("FV-101 fail closed");
    await expect(fic).toContainText("setpoint 3600 kg/h (given: basis of design) [design]");
    await expect(loops.locator('tr[data-loop="PIC-104"]')).toContainText("3 info");

    const start = page.locator('[data-sequence="SEQ-START"]');
    await expect(start).toContainText("Start permissives");
    await expect(start).toContainText("interlock I-01 reset");
    await expect(start).toContainText("LT-102 > 30 % for 30 s");
    await expect(start).toContainText("then SEQ-STOP");

    await expect(page.getByRole("region", { name: "Control philosophy" })).toContainText("Loss of instrument air");
    await expect(page.getByRole("region", { name: "Findings" })).toContainText("control-incomplete");
  });

  test("at another revision the links open the working tree the page shows", async ({ page }) => {
    await mockApi(page, { control: controlSeparation });
    await page.goto("/control?rev=abc1234");
    await expect(page.locator("[data-control-rev]")).toBeVisible();
    const link = page.getByRole("region", { name: "Files" }).getByRole("link", { name: "control/loops.yaml" });
    await expect(link).not.toHaveAttribute("href", /rev=/);
    // its seven findings are info, folded (#67)
    await page.getByTestId("info-findings").locator("summary").click();
    const finding = page.getByRole("region", { name: "Findings" }).getByRole("link").first();
    await expect(finding).not.toHaveAttribute("href", /rev=/);
  });

  test("a plant without control records shows no link, and the page says so", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    await expect(page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Control", exact: true })).toHaveCount(0);
    await page.goto("/control");
    await expect(page.locator("[data-control-missing]")).toContainText("No control records");
  });
});
