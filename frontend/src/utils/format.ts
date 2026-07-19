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

/** trilingual relative time: "१० मिनिटांपूर्वी / 2 hours ago / काल" (absolute in details) */
export function timeAgo(value: string | Date | number | null | undefined): string {
  if (!value) return "—";
  // required lazily to avoid an import cycle at module load
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const i18n = (require("@/src/i18n") as { default: { t: (k: string, o?: object) => string } }).default;
  const mins = Math.max(0, Math.floor((Date.now() - dayjs(value).valueOf()) / 60000));
  if (mins < 1) return i18n.t("time.justNow");
  if (mins < 60) return i18n.t("time.minsAgo", { count: mins });
  const hours = Math.floor(mins / 60);
  if (hours < 24) return i18n.t("time.hoursAgo", { count: hours });
  const days = Math.floor(hours / 24);
  if (days === 1) return i18n.t("time.yesterday");
  if (days < 7) return i18n.t("time.daysAgo", { count: days });
  return formatDate(value);
}

/** true when a pending item is older than 24h (approvals aging chip) */
export function isOlderThan24h(value: string | null | undefined): boolean {
  if (!value) return false;
  return Date.now() - dayjs(value).valueOf() > 24 * 3600 * 1000;
}
