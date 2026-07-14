import NetInfo from "@react-native-community/netinfo";
import { AppState, Platform } from "react-native";
import { create } from "zustand";

import { ApiError, uploadFile } from "@/src/api/client";
import { createIncident, punchIn } from "@/src/api/endpoints";
import { storage } from "@/src/utils/storage";

export interface OutboxItem {
  id: string;
  type: "incident" | "attendance";
  payload: Record<string, unknown>;
  photoUri: string | null;
  photoName: string;
  photoField: string; // payload key that receives the uploaded file key
  createdAt: number;
  retries: number;
  nextAttemptAt: number;
}

const STORE_KEY = "hogo.outbox";
const MAX_BACKOFF_MS = 10 * 60 * 1000;

interface OutboxState {
  items: OutboxItem[];
  processing: boolean;
  init: () => Promise<void>;
  enqueue: (item: Omit<OutboxItem, "id" | "createdAt" | "retries" | "nextAttemptAt">) => Promise<void>;
  process: () => Promise<void>;
}

async function persist(items: OutboxItem[]): Promise<void> {
  await storage.setItem(STORE_KEY, JSON.stringify(items));
}

async function copyIntoOutbox(uri: string, id: string): Promise<string> {
  if (Platform.OS === "web") return uri;
  try {
    const FileSystem = await import("expo-file-system/legacy");
    const dir = `${FileSystem.documentDirectory}outbox/`;
    await FileSystem.makeDirectoryAsync(dir, { intermediates: true }).catch(() => undefined);
    const dest = `${dir}${id}.jpg`;
    await FileSystem.copyAsync({ from: uri, to: dest });
    return dest;
  } catch {
    return uri;
  }
}

async function removeOutboxFile(uri: string | null): Promise<void> {
  if (!uri || Platform.OS === "web" || !uri.includes("outbox/")) return;
  try {
    const FileSystem = await import("expo-file-system/legacy");
    await FileSystem.deleteAsync(uri, { idempotent: true });
  } catch {
    // best effort
  }
}

let initialized = false;

export const useOutboxStore = create<OutboxState>((set, get) => ({
  items: [],
  processing: false,

  init: async () => {
    if (initialized) return;
    initialized = true;
    const raw = await storage.getItem<string>(STORE_KEY, "");
    if (raw) {
      try {
        set({ items: JSON.parse(raw) as OutboxItem[] });
      } catch {
        set({ items: [] });
      }
    }
    NetInfo.addEventListener((state) => {
      if (state.isConnected) void get().process();
    });
    AppState.addEventListener("change", (s) => {
      if (s === "active") void get().process();
    });
    void get().process();
  },

  enqueue: async (partial) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const photoUri = partial.photoUri ? await copyIntoOutbox(partial.photoUri, id) : null;
    const item: OutboxItem = {
      ...partial,
      photoUri,
      id,
      createdAt: Date.now(),
      retries: 0,
      nextAttemptAt: 0,
    };
    const items = [...get().items, item];
    set({ items });
    await persist(items);
    void get().process();
  },

  process: async () => {
    if (get().processing) return;
    const net = await NetInfo.fetch();
    if (!net.isConnected) return;
    set({ processing: true });
    try {
      for (const item of [...get().items]) {
        if (item.nextAttemptAt > Date.now()) continue;
        try {
          const payload: Record<string, unknown> = { ...item.payload };
          if (item.photoUri) {
            const uploaded = await uploadFile(item.photoUri, item.photoName);
            payload[item.photoField] = uploaded.key;
          }
          if (item.type === "incident") await createIncident(payload);
          else await punchIn(payload);
          const items = get().items.filter((i) => i.id !== item.id);
          set({ items });
          await persist(items);
          await removeOutboxFile(item.photoUri);
        } catch (e) {
          const status = e instanceof ApiError ? e.status : 0;
          if (status >= 400 && status < 500 && status !== 401 && status !== 429) {
            // permanent rejection (validation / duplicate punch) — drop it
            const items = get().items.filter((i) => i.id !== item.id);
            set({ items });
            await persist(items);
            await removeOutboxFile(item.photoUri);
          } else {
            const retries = item.retries + 1;
            const backoff = Math.min(5000 * 2 ** retries, MAX_BACKOFF_MS);
            const items = get().items.map((i) =>
              i.id === item.id ? { ...i, retries, nextAttemptAt: Date.now() + backoff } : i,
            );
            set({ items });
            await persist(items);
          }
        }
      }
    } finally {
      set({ processing: false });
    }
  },
}));
