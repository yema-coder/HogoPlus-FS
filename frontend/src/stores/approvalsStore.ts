import dayjs from "dayjs";
import { create } from "zustand";

import {
  flaggedAttendance,
  listIncidents,
  listSubmissions,
  pendingEmployees,
  pendingSwaps,
} from "@/src/api/endpoints";

export interface ApprovalCounts {
  forms: number;
  regs: number;
  swaps: number;
  incidents: number;
  attendance: number;
}

interface ApprovalsState {
  counts: ApprovalCounts;
  total: number;
  refresh: (includeAttendance: boolean) => Promise<void>;
  adjust: (key: keyof ApprovalCounts, delta: number) => void;
}

const ZERO: ApprovalCounts = { forms: 0, regs: 0, swaps: 0, incidents: 0, attendance: 0 };

const sum = (c: ApprovalCounts) => c.forms + c.regs + c.swaps + c.incidents + c.attendance;

/** Pending counts feeding the Approvals tab badge. */
export const useApprovalsStore = create<ApprovalsState>((set, get) => ({
  counts: ZERO,
  total: 0,
  refresh: async (includeAttendance) => {
    const [subs, escSubs, regs, swaps, incSub, incEsc, att] = await Promise.allSettled([
      listSubmissions({ status: "submitted", page_size: 1 }),
      listSubmissions({ status: "escalated", page_size: 1 }),
      pendingEmployees(),
      pendingSwaps(),
      listIncidents({ status: "submitted" }),
      listIncidents({ status: "escalated" }),
      includeAttendance ? flaggedAttendance(dayjs().format("YYYY-MM-DD")) : Promise.resolve([]),
    ]);
    const counts: ApprovalCounts = {
      forms:
        (subs.status === "fulfilled" ? subs.value.total : 0) +
        (escSubs.status === "fulfilled" ? escSubs.value.total : 0),
      regs: regs.status === "fulfilled" ? regs.value.length : 0,
      swaps: swaps.status === "fulfilled" ? swaps.value.length : 0,
      incidents:
        (incSub.status === "fulfilled" ? incSub.value.length : 0) +
        (incEsc.status === "fulfilled" ? incEsc.value.length : 0),
      attendance: att.status === "fulfilled" ? att.value.length : 0,
    };
    set({ counts, total: sum(counts) });
  },
  adjust: (key, delta) => {
    const counts = { ...get().counts, [key]: Math.max(0, get().counts[key] + delta) };
    set({ counts, total: sum(counts) });
  },
}));
