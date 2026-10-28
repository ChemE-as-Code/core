import { describe, expect, it } from "vitest";
import type { PlantStatus } from "@/api";
import { parseMarkdown } from "@/lib/markdown";
import {
  closingCommit,
  filterRegister,
  findingMarkdown,
  hasReviewData,
  idStem,
  isBlocking,
  isRecordPath,
  openFindings,
  parseRecord,
  register,
  severityCounts,
  signoffsFromStatusFile,
  sortRecords,
  statusKind,
  summarizeRecords,
} from "@/lib/reviews";
import reviewsJson from "./fixtures/api/reviews-asu.json";
import statusJson from "./fixtures/api/status-asu.json";

const status = statusJson as unknown as PlantStatus;
const texts = reviewsJson as Record<string, string>;
const asuRecords = () => sortRecords(Object.entries(texts).filter(([path]) => isRecordPath(path)).map(([path, text]) => parseRecord(path, text)));

const FIRST = `---
topic: layout
reviewed_commit: "abc1234def"
scope: [layout/site-plan.yaml]
reviewer: R. Viewer
reviewer_kind: human
---
# Layout review

## Findings

| id | severity | finding | status |
|---|---|---|---|
| 2026-10-01-layout#1 | **High** | Rack too low<br>- at PR1<br>- at PR2 | open |
| 2026-10-01-layout#2 | low | Pipe \\| crossing | closed 1234567 |
| 2026-10-01-layout#3 | medium | Ladder | accepted: by design, A. B. |
| bad id | low | not counted | open |
`;
const SECOND = `---
topic: layout
reviewed_commit: fff0000
reviewer: Agent
reviewer_kind: agent
---
## Findings

| id | severity | finding | status |
|---|---|---|---|
| 2026-10-05-layout#1 | critical | O2 line | open |

## Previous findings

| id | severity | finding | status |
|---|---|---|---|
| 2026-10-01-layout#1 | high | Rack too low | superseded by 2026-10-05-layout#1 |
| 2026-10-01-layout#3 | medium | Ladder | partly closed |
`;

describe("review records", () => {
  it("statuses, as core's vocabulary has them", () => {
    expect(statusKind("open")).toBe("open");
    expect(statusKind("`closed 1a2b3c4`")).toBe("closed");
    expect(closingCommit("closed 1a2b3c4 (fix)")).toBe("1a2b3c4");
    expect(statusKind("closed soon")).toBeNull();
    expect(statusKind("accepted: by design")).toBe("accepted");
    expect(statusKind("superseded by x#2")).toBe("superseded");
    expect(statusKind("partly closed")).toBeNull();
    expect(isBlocking("Major")).toBe(true);
    expect(isBlocking("medium")).toBe(false);
    expect(idStem("2026-10-18-o2-safety#3")).toBe("2026-10-18-o2-safety");
    expect(idStem("F1")).toBeNull();
    expect(isRecordPath("reviews/2026-10-01-x.md")).toBe(true);
    expect(isRecordPath("reviews/README.md")).toBe(false);
    expect(isRecordPath("reviews/sub/notes.md")).toBe(false);
  });

  it("parses front matter and finding tables", () => {
    const r = parseRecord("reviews/2026-10-01-layout.md", FIRST);
    expect(r.front).toMatchObject({ topic: "layout", reviewed_commit: "abc1234def", reviewer: "R. Viewer", reviewer_kind: "human" });
    expect(r.date).toBe("2026-10-01");
    expect(r.rows.map((x) => x.id)).toEqual(["2026-10-01-layout#1", "2026-10-01-layout#2", "2026-10-01-layout#3", "bad id"]);
    expect(r.rows[0]).toMatchObject({ severity: "high", status: "open", section: "findings", line: 14 });
    expect(r.rows[1]!.finding).toBe("Pipe \\| crossing");
    expect(parseRecord("reviews/x.md", "# no front\n").front).toBeNull();
  });

  it("the latest record decides a finding's status", () => {
    const records = sortRecords([parseRecord("reviews/2026-10-05-layout.md", SECOND), parseRecord("reviews/2026-10-01-layout.md", FIRST)]);
    const open = openFindings(records);
    // #1 superseded, #2 closed, #3 "partly closed" is not a status: still open (as core counts it)
    expect(open.map((f) => f.id)).toEqual(["2026-10-01-layout#3", "2026-10-05-layout#1"]);
    expect(open[0]!.record).toBe("reviews/2026-10-05-layout.md");

    const [newest, oldest] = summarizeRecords(records);
    expect(newest!.record.stem).toBe("2026-10-05-layout");
    expect(newest).toMatchObject({ raised: 1, open: 1, blocking: 1 });
    expect(oldest).toMatchObject({ raised: 3, open: 1, closed: 1, accepted: 0, superseded: 1, blocking: 0 });

    const rows = register(open, records);
    expect(rows[0]).toMatchObject({ id: "2026-10-05-layout#1", blocking: true, origin: "reviews/2026-10-05-layout.md", reviewedCommit: "fff0000" });
    expect(rows[1]).toMatchObject({ id: "2026-10-01-layout#3", origin: "reviews/2026-10-01-layout.md", reviewedCommit: "fff0000" });
    expect(filterRegister(rows, { severity: "blocking" }).map((r) => r.id)).toEqual(["2026-10-05-layout#1"]);
    expect(filterRegister(rows, { severity: "medium" }).map((r) => r.id)).toEqual(["2026-10-01-layout#3"]);
    expect(filterRegister(rows, { record: "reviews/2026-10-01-layout.md" }).map((r) => r.id)).toEqual(["2026-10-01-layout#3"]);
    expect(severityCounts(open)).toEqual([
      { severity: "critical", count: 1 },
      { severity: "medium", count: 1 },
    ]);
  });

  it("derives the same open findings as cheme status from the ASU's records", () => {
    const records = asuRecords();
    expect(records.length).toBe(status.reviews.records);
    expect(openFindings(records)).toEqual(status.reviews.open);
    const summaries = summarizeRecords(records, status.reviews.open);
    expect(summaries.reduce((n, s) => n + s.open, 0)).toBe(status.reviews.open.length);
    // every record raised findings that are closed or accepted by now
    expect(summaries.reduce((n, s) => n + s.closed + s.accepted + s.superseded, 0)).toBeGreaterThan(status.reviews.open.length);
    const rows = register(status.reviews.open, records);
    expect(rows.every((r) => r.origin && r.reviewedCommit)).toBe(true);
  });

  it("turns a finding cell into Markdown with lists", () => {
    const md = findingMarkdown("Four stubs:<br>- SP-8.9: base 3.79;<br>- SP-11.0: base 3.29.<br>Each stands on a crossbar.");
    const blocks = parseMarkdown(md);
    expect(blocks.map((b) => b.t)).toEqual(["paragraph", "list", "paragraph"]);
    expect(blocks.find((b) => b.t === "list")).toMatchObject({ items: { length: 2 } });
  });
});

describe("sign-offs", () => {
  it("reads checks/status.json stages, the 0.3 kind as none", () => {
    const text = JSON.stringify({ stages: { basic: { commit: "abc", date: "2026-10-23", signed_by: "A", review: "reviews/x.md" }, bad: 3 } });
    expect(signoffsFromStatusFile(text)).toEqual({
      basic: { commit: "abc", date: "2026-10-23", signed_by: "A", branch: null, review: "reviews/x.md", reviewer_kind: null, on_default_branch: null },
    });
    expect(signoffsFromStatusFile(JSON.stringify({ checks: [{ id: "x" }] }))).toEqual({});
    expect(signoffsFromStatusFile("not json")).toEqual({});
    expect(signoffsFromStatusFile(null)).toEqual({});
  });

  it("offers the Reviews page unless the status has neither records nor sign-offs", () => {
    expect(hasReviewData(null)).toBe(true);
    expect(hasReviewData(status)).toBe(true);
    expect(hasReviewData({ ...status, reviews: { records: 0, open: [] }, signoffs: {} })).toBe(false);
  });
});
