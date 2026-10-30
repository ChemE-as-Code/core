import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { controlSeparation, issuesSeparation, mockApi, SHEET } from "./fixtures";

/**
 * The issues page and the "New issue" links: core's examples/process-separation with `issues:`
 * in plant.yaml (`/api/issues`, GitHub stubbed): stage basic, #1-#9 with every type, gate and
 * status, #4 closed, #7 untyped.
 */
test.describe("issues", () => {
  test("open items by gate, the blocking count, badges, filters and closed items", async ({ page }) => {
    await mockApi(page, { issues: issuesSeparation });
    await page.goto("/");
    await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Issues" }).click();
    await expect(page).toHaveURL(/\/issues/);

    await expect(page.locator("[data-issues-blocking]")).toHaveText("5");
    await expect(page.locator("[data-issues-summary]")).toContainText("block the Basic engineering gate (#9, #8, #3, #2, #1)");

    await expect(page.locator("section[data-gate]")).toHaveCount(5);
    const gates = await page.locator("section[data-gate]").evaluateAll((els) => els.map((e) => e.getAttribute("data-gate")));
    expect(gates).toEqual(["concept", "basic", "detail", "Basic", "none"]);
    await expect(page.locator('[data-issue="8"] [data-gates]')).toHaveText("gates concept, basic");
    await expect(page.locator('[data-issue="9"] [data-unknown-gate]')).toBeVisible();

    const hold = page.locator('[data-issue="2"]');
    await expect(hold.locator("[data-type]")).toHaveText("Engineering hold");
    await expect(hold.locator("[data-waiting]")).toHaveText("waiting for input");
    await expect(hold.locator("[data-disciplines]")).toHaveText("mechanical, process");
    await expect(hold.locator("[data-source]")).toHaveText("from vendor");
    await expect(hold.getByRole("link", { name: "#2" })).toHaveAttribute("href", "https://github.com/ChemE-as-Code/process-library/issues/2");
    await expect(page.locator('[data-issue="1"] [data-type]')).toHaveText("Technical query (TQ)");
    await expect(page.locator('[data-issue="1"] [data-status]')).toHaveText("for verification");
    await expect(page.locator('[data-issue="5"] [data-type]')).toHaveText("Design change");
    await expect(page.locator('[data-issue="7"] [data-type]')).toHaveText("Untyped");

    const tq = page.locator('[data-new="tq"]');
    await expect(tq).toHaveText("New technical query (TQ)");
    await expect(tq).toHaveAttribute("href", issuesSeparation.new.tq);
    await expect(page.locator("[data-new]")).toHaveCount(4);

    await expect(page.locator('[data-issue="4"]')).toHaveCount(0);
    await page.locator('[data-action="closed"]').check();
    await expect(page.locator('[data-issue="4"] [data-status]')).toHaveText("closed");
    await expect(page).toHaveURL(/closed=1/);

    await page.locator('[data-action="type"]').selectOption("action");
    await expect(page.locator("[data-issue]")).toHaveCount(4);
    await page.locator('[data-action="discipline"]').selectOption("safety");
    await expect(page.locator("[data-issue]")).toHaveCount(2);
    await page.locator('[data-action="gate"]').selectOption("none");
    await expect(page.locator("[data-issue]")).toHaveCount(1);
    await expect(page.locator('[data-issue="6"]')).toBeVisible();
    await page.locator('[data-action="gate"]').selectOption("");
    await page.locator('[data-action="discipline"]').selectOption("");
    await page.locator('[data-action="type"]').selectOption("");
    await page.locator('[data-action="status"]').selectOption("in-progress");
    await expect(page.locator("[data-issue]")).toHaveCount(1);
    await expect(page.locator('[data-issue="3"]')).toBeVisible();
  });

  test("at another revision it says it shows the issues as they are now", async ({ page }) => {
    await mockApi(page, { issues: issuesSeparation });
    await page.goto("/issues?rev=abc1234");
    await expect(page.locator("[data-issues-rev]")).toContainText("as GitHub has them now");
    await expect(page.locator("[data-issue]").first()).toBeVisible();
  });

  test("a plant without issues has no link, and the page says so", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    await expect(page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Issues" })).toHaveCount(0);
    await page.goto("/issues");
    await expect(page.locator("[data-issues-missing]")).toContainText("This plant does not track issues");
  });

  test("issues that cannot be read: the message and how to give a token, and no New issue links", async ({ page }) => {
    await mockApi(page, { issues: "unavailable", control: controlSeparation });
    await page.goto("/issues");
    const notice = page.locator("[data-issues-unavailable]");
    await expect(notice).toContainText("no GitHub token");
    await expect(notice).toContainText("GITHUB_TOKEN");
    await expect(notice).toContainText("gh auth login");
    await page.goto("/control");
    await expect(page.locator('tr[data-loop="FIC-101"]')).toBeVisible();
    await expect(page.locator('[data-action="new-issue"]')).toHaveCount(0);
  });

  test("New issue about a P&ID tag and a control loop, /api/issues loaded once", async ({ page }) => {
    let requests = 0;
    page.on("request", (r) => {
      if (new URL(r.url()).pathname === "/api/issues") requests += 1;
    });
    await mockApi(page, { issues: issuesSeparation, control: controlSeparation });
    await page.goto(`/pid/${SHEET}?select=P-101`);
    const link = page.locator('.info [data-action="new-issue"]');
    await expect(link).toHaveText("New issue about P-101");
    await expect(link).toHaveAttribute("href", `${issuesSeparation.new.action}&refs=P-01%20P-101`);
    // another pick: the same cached answer
    await page.locator('.pane[role="application"] [id="Tank1"] rect').click();
    await expect(link).toHaveText("New issue about T-101");
    await expect(link).toHaveAttribute("href", /refs=P-01%20T-101$/);

    await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Control", exact: true }).click();
    const loop = page.locator('tr[data-loop="PIC-104"] [data-action="new-issue"]');
    await expect(loop).toHaveText("New issue about PIC-104");
    await expect(loop).toHaveAttribute("href", `${issuesSeparation.new.action}&refs=control%2Floops.yaml%20PIC-104`);
    await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Issues" }).click();
    await expect(page.locator("[data-issue]").first()).toBeVisible();
    expect(requests).toBe(1);
  });
});

const SNAPSHOT = resolve(dirname(fileURLToPath(import.meta.url)), "snapshot");

test("a snapshot of a plant with issues but without them recorded: the page says so", async ({ page }) => {
  const manifest = JSON.parse(readFileSync(join(SNAPSHOT, "manifest.json"), "utf-8"));
  const repoFile = `data/${manifest.entries.repo.file}`;
  await page.route((url) => url.pathname.startsWith("/e2e-snapshot/"), async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/e2e-snapshot\//, "");
    if (path === repoFile) {
      const repo = JSON.parse(readFileSync(join(SNAPSHOT, path), "utf-8"));
      return route.fulfill({ contentType: "application/json", body: JSON.stringify({ ...repo, has_issues: true }) });
    }
    try {
      await route.fulfill({ body: readFileSync(join(SNAPSHOT, path)) });
    } catch {
      await route.fulfill({ status: 404, body: "not found" });
    }
  });
  await page.route((url) => url.pathname.startsWith("/api/"), (route) => route.abort());
  await page.goto("/?data=/e2e-snapshot/#/pid/process/PFD.xml");
  await expect(page.locator(".pane[role='application'] svg").first()).toBeVisible();
  await page.locator(".pane[role='application'] .representation-group").first().click({ force: true });
  await expect(page.locator(".info")).toBeVisible();
  await expect(page.locator('[data-action="new-issue"]')).toHaveCount(0);
  await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Issues" }).click();
  await expect(page.locator("[data-issues-not-exported]")).toContainText("This snapshot does not hold the issues");
});
