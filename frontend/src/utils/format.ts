import dayjs from "dayjs";

/** DD/MM/YYYY */
export function formatDate(value: string | Date | number | null | undefined): string {
  if (!value) return "—";
  return dayjs(value).format("DD/MM/YYYY");
}

/** 12-hour time, e.g. 02:35 PM */
export function formatTime(value: string | Date | number | null | undefined): string {
  if (!value) return "—";
  return dayjs(value).format("hh:mm A");
}

export function formatDateTime(value: string | Date | number | null | undefined): string {
  if (!value) return "—";
  return dayjs(value).format("DD/MM/YYYY hh:mm A");
}

/** "HH:MM:SS" shift time → 12-hour label */
export function formatShiftTime(t: string | null | undefined): string {
  if (!t) return "—";
  return dayjs(`2000-01-01T${t}`).format("hh:mm A");
}

/** minutes elapsed → "Xh Ym" */
export function formatElapsed(fromIso: string): string {
  const mins = Math.max(0, Math.floor((Date.now() - dayjs(fromIso).valueOf()) / 60000));
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

/** age in whole minutes for "updated Xm ago" */
export function minutesAgo(ts: number): number {
  return Math.max(0, Math.floor((Date.now() - ts) / 60000));
}
