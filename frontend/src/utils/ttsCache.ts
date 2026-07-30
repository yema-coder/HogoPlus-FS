import { Platform } from "react-native";

import { api, fileUrl } from "@/src/api/client";
import { storage } from "@/src/utils/storage";

const MAP_KEY = "hogo.tts.map";
const MAX_ENTRIES = 200;

/** FNV-1a, two passes (forward + reverse) — local cache key only; the server
 * keys its own cache independently by sha256 of the text. */
export function hashText(text: string): string {
  let h1 = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h1 ^= text.charCodeAt(i);
    h1 = Math.imul(h1, 0x01000193);
  }
  let h2 = 0x811c9dc5;
  for (let i = text.length - 1; i >= 0; i--) {
    h2 ^= text.charCodeAt(i);
    h2 = Math.imul(h2, 0x01000193);
  }
  return (h1 >>> 0).toString(16) + (h2 >>> 0).toString(16);
}

async function readMap(): Promise<Record<string, string>> {
  const raw = await storage.getItem<string>(MAP_KEY, "");
  if (!raw) return {};
  try {
    return JSON.parse(raw) as Record<string, string>;
  } catch {
    return {};
  }
}

async function writeMap(map: Record<string, string>): Promise<void> {
  const keys = Object.keys(map);
  if (keys.length > MAX_ENTRIES) {
    for (const k of keys.slice(0, keys.length - MAX_ENTRIES)) delete map[k];
  }
  await storage.setItem(MAP_KEY, JSON.stringify(map));
}

/** Resolve a playable uri for the text: on-device mp3 cache first (works
 * OFFLINE for anything played before), else POST /ai/tts (server returns its
 * hash-cached audio without regenerating) and download for next time. */
export async function getTtsUri(text: string): Promise<string> {
  const h = hashText(text);
  const map = await readMap();
  const cached = map[h];
  if (cached) {
    if (Platform.OS === "web") return cached;
    try {
      const FileSystem = await import("expo-file-system/legacy");
      const info = await FileSystem.getInfoAsync(cached);
      if (info.exists) return cached;
    } catch {
      // stale entry — fall through and re-fetch
    }
  }
  const res = await api<{ key: string; url: string; cached: boolean }>("/ai/tts", {
    method: "POST",
    body: { text },
  });
  const remote = fileUrl(res.key);
  if (Platform.OS === "web") {
    map[h] = remote;
    await writeMap(map);
    return remote;
  }
  const FileSystem = await import("expo-file-system/legacy");
  const dir = `${FileSystem.cacheDirectory}tts/`;
  await FileSystem.makeDirectoryAsync(dir, { intermediates: true }).catch(() => undefined);
  const dl = await FileSystem.downloadAsync(remote, `${dir}${h}.mp3`);
  map[h] = dl.uri;
  await writeMap(map);
  return dl.uri;
}
