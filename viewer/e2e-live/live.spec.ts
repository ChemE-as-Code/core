import { expect, test } from "@playwright/test";

// Against a live `cheme serve --ui dist` (playwright.live.config.ts): the viewer and the API of
// the same commit. The plant is examples/safety-hazop as a git repository.

test("the API answers the viewer's first requests", async ({ request }) => {
  for (const path of ["/api/repo", "/api/tree", "/api/branches", "/api/log"]) {
    const response = await request.get(path);
    expect(response.ok(), path).toBeTruthy();
  }
});

test("file tree, P&ID and checks page from the live server", async ({ page }) => {
  const failed: string[] = [];
  page.on("response", (r) => {
    if (r.url().includes("/api/") && r.status() >= 500) failed.push(`${r.status()} ${r.url()}`);
  });
  await page.goto("/");
  await expect(page.getByText("P-01.xml").first()).toBeVisible();
  await page.goto("/pid/pid/P-01.xml");
  await expect(page.locator(".pid .pane svg").first()).toBeAttached();
  await page.goto("/checks");
  await expect(page.locator("main, #app").first()).toBeVisible();
  expect(failed).toEqual([]);
});
