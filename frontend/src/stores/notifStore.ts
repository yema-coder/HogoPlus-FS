import { create } from "zustand";

interface NotifState {
  unread: number;
  setUnread: (n: number) => void;
}

/** Shared unread-alerts counter feeding the tab-bar badge. */
export const useNotifStore = create<NotifState>((set) => ({
  unread: 0,
  setUnread: (unread) => set({ unread }),
}));
