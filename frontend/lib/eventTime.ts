/**
 * eventTime.ts — event timestamps are stored and returned as UTC ("…Z").
 * Always go through these helpers so the dashboard widget, the Events page and
 * the Calendar show the same event at the same local time.
 */

/** Parse an API event_date as UTC (older responses may lack the trailing Z). */
export function parseEventDate(value: string): Date {
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
}

/** API event_date → value for an <input type="datetime-local"> (viewer's local time). */
export function toDateTimeLocalInput(value: string): string {
  const d = parseEventDate(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** <input type="datetime-local"> value (local time) → UTC ISO string for the API. */
export function fromDateTimeLocalInput(value: string): string {
  return new Date(value).toISOString();
}
