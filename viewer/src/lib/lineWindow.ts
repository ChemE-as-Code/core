/**
 * Which lines of a file to render as numbered rows. A table row per line is too slow for very
 * long files (a P&ID sheet has tens of thousands of lines), but "open at line" needs a row to
 * scroll to. So: short files get every row; a long file opened at a line gets the rows around
 * it; a long file without a line is shown as plain text (`null`).
 */
export const MAX_ROWS = 4000;
export const WINDOW_RADIUS = 200;

export interface LineWindow {
  /** First line shown, 1-based. */
  first: number;
  /** Last line shown, 1-based, inclusive. */
  last: number;
  /** Whether lines are left out. */
  partial: boolean;
}

export function lineWindow(
  total: number,
  target: number | null,
  maxRows: number = MAX_ROWS,
  radius: number = WINDOW_RADIUS,
): LineWindow | null {
  if (total <= maxRows) return { first: 1, last: total, partial: false };
  if (!target) return null;
  const line = Math.min(Math.max(1, target), total);
  const first = Math.max(1, line - radius);
  const last = Math.min(total, line + radius);
  return { first, last, partial: first > 1 || last < total };
}
