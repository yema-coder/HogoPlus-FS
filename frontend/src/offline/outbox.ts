import NetInfo from "@react-native-community/netinfo";
import { AppState, Platform } from "react-native";
import { create } from "zustand";

import { ApiError, uploadFile } from "@/src/api/client";
import { createIncident, createVehicleLog, punchIn, submitForm } from "@/src/api/endpoints";
import { storage } from "@/src/utils/storage";

export interface OutboxFile {
  /** data_json key that receives the uploaded file key */
  field: string;
  uri: string;
  name: string;
  kind: "photo" | "audio";
}

export interface OutboxItem {
  id: string;
  type: "incident" | "attendance" | "form" | "vehicle";
  payload: Record<string, unknown>;
  photoUri: string | null;
  photoName: string;
  photoField: string; // payload key that receives the uploaded file key
  /** form submissions may carry multiple photos / voice notes */
  files?: OutboxFile[];
  createdAt: number;
  retries: number;
  nextAttemptAt: number;
}

const STORE_KEY = "hogo.outbox";
const MAX_BACKOFF_MS = 10 * 60 * 1000;

interface OutboxState {
  items: OutboxItem[];
  processing: boolean;
  /** id of the item currently being uploaded (drives "Uploading…" chips) */
  uploadingId: string | null;
  /** outbox item id → created incident id (null = permanently rejected) */
  results: Record<string, string | null>;
  init: () => Promise<void>;
  enqueue: (item: Omit<OutboxItem, "id" | "createdAt" | "retries" | "nextAttemptAt">) => Promise<string>;
  process: () => Promise<void>;
}

async function persist(items: OutboxItem[]): Promise<void> {
  await storage.setItem(STORE_KEY, JSON.stringify(items));
}

async function copyIntoOutbox(uri: string, fileName: string): Promise<string> {
  if (Platform.OS === "web") return uri;
  try {
    const FileSystem = await import("expo-file-system/legacy");
    const dir = `${FileSystem.documentDirectory}outbox/`;
    await FileSystem.makeDirectoryAsync(dir, { intermediates: true }).catch(() => undefined);
    const dest = `${dir}${fileName}`;
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
  uploadingId: null,
  results: {},

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
    const photoUri = partial.photoUri ? await copyIntoOutbox(partial.photoUri, `${id}.jpg`) : null;
    let files: OutboxFile[] | undefined;
    if (partial.files) {
      files = [];
      for (const f of partial.files) {
        files.push({ ...f, uri: await copyIntoOutbox(f.uri, `${id}-${f.field}-${f.name}`) });
      }
    }
    const item: OutboxItem = {
      ...partial,
      photoUri,
      files,
      id,
      createdAt: Date.now(),
      retries: 0,
      nextAttemptAt: 0,
    };
    const items = [...get().items, item];
    set({ items });
    await persist(items);
    void get().process();
    return id;
  },

  process: async () => {
    if (get().processing) return;
    const net = await NetInfo.fetch();
    if (!net.isConnected) return;
    set({ processing: true });
    try {
      for (const item of [...get().items]) {
        if (item.nextAttemptAt > Date.now()) continue;
        set({ uploadingId: item.id });
        try {
          const payload: Record<string, unknown> = { ...item.payload };
          if (item.photoUri) {
            const uploaded = await uploadFile(item.photoUri, item.photoName);
            payload[item.photoField] = uploaded.key;
          }
          if (item.type === "incident") {
            // aux files (voice note): a non-network failure must not block the report
            for (const f of item.files ?? []) {
              try {
                const up = await uploadFile(f.uri, f.name);
                payload[f.field] = up.key;
              } catch (fe) {
                if (fe instanceof ApiError && fe.status === 0) throw fe;
              }
            }
            const created = (await createIncident(payload)) as { id?: string };
            set({ results: { ...get().results, [item.id]: created.id ?? null } });
          } else if (item.type === "attendance") await punchIn(payload);
          else if (item.type === "vehicle") {
            // voice note is best-effort; the log itself must never be blocked by it
            for (const f of item.files ?? []) {
              try {
                const up = await uploadFile(f.uri, f.name);
                payload[f.field] = up.key;
              } catch (fe) {
                if (fe instanceof ApiError && fe.status === 0) throw fe;
              }
            }
            await createVehicleLog(payload); // client_uuid makes replays idempotent
          }
          else {
            // form submission: upload each queued file, patch data_json, submit
            const data = { ...(payload.data_json as Record<string, unknown>) };
            const photoKeys: string[] = [];
            for (const f of item.files ?? []) {
              const uploaded = await uploadFile(f.uri, f.name);
              data[f.field] = uploaded.key;
              if (f.kind === "photo") photoKeys.push(uploaded.key);
            }
            await submitForm(String(payload.definition_id), {
              data_json: data,
              photos: photoKeys,
              gps_lat: (payload.gps_lat as number | null) ?? null,
              gps_lng: (payload.gps_lng as number | null) ?? null,
            });
          }
          const items = get().items.filter((i) => i.id !== item.id);
          set({ items });
          await persist(items);
          await removeOutboxFile(item.photoUri);
          for (const f of item.files ?? []) await removeOutboxFile(f.uri);
        } catch (e) {
          const status = e instanceof ApiError ? e.status : 0;
          if (status >= 400 && status < 500 && status !== 401 && status !== 429) {
            // permanent rejection (validation / duplicate punch) — drop it
            const items = get().items.filter((i) => i.id !== item.id);
            set({ items, results: { ...get().results, [item.id]: null } });
            await persist(items);
            await removeOutboxFile(item.photoUri);
            for (const f of item.files ?? []) await removeOutboxFile(f.uri);
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
      set({ processing: false, uploadingId: null });
    }
  },
}));
