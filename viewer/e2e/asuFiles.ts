import { readFileSync } from "node:fs";

/** Files of the ASU repository the layout view reads beside the model (`mockApi(page, { files })`). */
export const asuFiles: Record<string, string> = {
  "layout/lifting-study.csv": readFileSync(new URL("../tests/fixtures/api/lifting-study-asu.csv", import.meta.url), "utf-8"),
  "electrical/cable-schedule.csv": readFileSync(new URL("../tests/fixtures/api/cable-schedule-asu.csv", import.meta.url), "utf-8"),
};
