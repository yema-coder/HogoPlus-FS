import { Platform } from "react-native";

import { storage } from "@/src/utils/storage";

const BASE = (process.env.EXPO_PUBLIC_API_URL ?? "").replace(/\/+$/, "");

// LAUNCH GUARD (v1.0.13 field failure, 2026-07-28): the build pipeline's env
// injection ("STEP 2: Configuring backend URL") can replace or EMPTY
// EXPO_PUBLIC_API_URL, which bakes a relative "/api" base into the release
// bundle — every request then dies instantly with a network error. In any
// RELEASE build the API base is therefore pinned to the production host; the
// env value is only honoured in dev (__DEV__: Expo Go / web preview / metro),
// so sandbox testing keeps working.
const PROD_API_URL = "https://api.hogoplus.in";
let resolvedBase: string;
if (__DEV__) {
  resolvedBase = BASE || PROD_API_URL;
} else {
  if (BASE !== PROD_API_URL) {
    console.warn(
      `[api] EXPO_PUBLIC_API_URL ${BASE ? `was "${BASE}"` : "is EMPTY"} in a release build — using ${PROD_API_URL}`,
    );
  }
  resolvedBase = PROD_API_URL;
}
export const API_BASE = `${resolvedBase}/api`;

const ACCESS_KEY = "hogo.access";
const REFRESH_KEY = "hogo.refresh";
const TIMEOUT_MS = 15000;

let accessToken: string | null = null;
let refreshToken: string | null = null;
let sessionExpiredHandler: (() => void) | null = null;
let refreshing: Promise<boolean> | null = null;

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

export function setSessionExpiredHandler(fn: () => void): void {
  sessionExpiredHandler = fn;
}

export async function hydrateTokens(): Promise<boolean> {
  const a = await storage.secureGet<string>(ACCESS_KEY, "");
  const r = await storage.secureGet<string>(REFRESH_KEY, "");
  accessToken = a ? a : null;
  refreshToken = r ? r : null;
  return accessToken !== null;
}

export async function setTokens(access: string, refresh: string): Promise<void> {
  accessToken = access;
  refreshToken = refresh;
  await storage.secureSet(ACCESS_KEY, access);
  await storage.secureSet(REFRESH_KEY, refresh);
}

export async function clearTokens(): Promise<void> {
  accessToken = null;
  refreshToken = null;
  await storage.secureRemove(ACCESS_KEY);
  await storage.secureRemove(REFRESH_KEY);
}

export function hasSession(): boolean {
  return accessToken !== null;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  formData?: FormData;
  auth?: boolean;
  tokenOverride?: string;
}

async function doFetch(path: string, opts: RequestOptions, token: string | null): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const headers: Record<string, string> = {};
    if (!opts.formData) headers["Content-Type"] = "application/json";
    if (token) headers.Authorization = `Bearer ${token}`;
    return await fetch(`${API_BASE}${path}`, {
      method: opts.method ?? "GET",
      headers,
      body: opts.formData ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

async function tryRefresh(): Promise<boolean> {
  if (!refreshToken) return false;
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const res = await doFetch("/auth/refresh", { method: "POST", body: { refresh_token: refreshToken } }, null);
        if (!res.ok) return false;
        const data = (await res.json()) as { access_token: string; refresh_token: string };
        await setTokens(data.access_token, data.refresh_token);
        return true;
      } catch {
        return false;
      } finally {
        refreshing = null;
      }
    })();
  }
  return refreshing;
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const useAuth = opts.auth !== false;
  const token = opts.tokenOverride ?? (useAuth ? accessToken : null);
  let res: Response;
  try {
    res = await doFetch(path, opts, token);
  } catch (e) {
    throw new ApiError(0, e instanceof Error && e.name === "AbortError" ? "timeout" : "network");
  }

  if (res.status === 401 && useAuth && !opts.tokenOverride && refreshToken) {
    const ok = await tryRefresh();
    if (ok) {
      try {
        res = await doFetch(path, opts, accessToken);
      } catch (e) {
        throw new ApiError(0, e instanceof Error && e.name === "AbortError" ? "timeout" : "network");
      }
    } else {
      await clearTokens();
      sessionExpiredHandler?.();
      throw new ApiError(401, "session_expired");
    }
  }

  if (!res.ok) {
    let detail: unknown = null;
    try {
      const parsed = (await res.json()) as { detail?: unknown };
      detail = parsed.detail ?? parsed;
    } catch {
      detail = res.statusText;
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

const MIME_BY_EXT: Record<string, string> = {
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
  webp: "image/webp",
  m4a: "audio/m4a",
  mp3: "audio/mpeg",
  mp4: "video/mp4",
  mov: "video/quicktime",
  pdf: "application/pdf",
};

export async function uploadFile(
  uri: string,
  name: string,
  tokenOverride?: string,
): Promise<{ key: string; url: string }> {
  const ext = name.includes(".") ? name.split(".").pop()!.toLowerCase() : "jpg";
  const mime = MIME_BY_EXT[ext] ?? "image/jpeg";
  if (Platform.OS === "web") {
    const fd = new FormData();
    const blob = await (await fetch(uri)).blob();
    fd.append("file", blob, name);
    return api<{ key: string; url: string }>("/files/upload", {
      method: "POST",
      formData: fd,
      tokenOverride,
    });
  }
  // Native: RN's fetch + FormData can post an EMPTY file part on Android (Expo Go),
  // which the backend rejects with 400 "Empty file". expo-file-system's native
  // uploader streams the file reliably on both platforms.
  const FileSystem = await import("expo-file-system/legacy");
  const doUpload = (token: string | null) =>
    FileSystem.uploadAsync(`${API_BASE}/files/upload`, uri, {
      httpMethod: "POST",
      uploadType: FileSystem.FileSystemUploadType.MULTIPART,
      fieldName: "file",
      mimeType: mime,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  let res: { status: number; body: string };
  try {
    res = await doUpload(tokenOverride ?? accessToken);
  } catch {
    throw new ApiError(0, "network");
  }
  if (res.status === 401 && !tokenOverride && refreshToken) {
    const ok = await tryRefresh();
    if (!ok) {
      await clearTokens();
      sessionExpiredHandler?.();
      throw new ApiError(401, "session_expired");
    }
    try {
      res = await doUpload(accessToken);
    } catch {
      throw new ApiError(0, "network");
    }
  }
  if (res.status >= 400) {
    let detail: unknown = res.body;
    try {
      detail = (JSON.parse(res.body) as { detail?: unknown }).detail ?? res.body;
    } catch {
      // keep raw body
    }
    throw new ApiError(res.status, detail);
  }
  return JSON.parse(res.body) as { key: string; url: string };
}

export function fileUrl(key: string): string {
  return `${API_BASE}/files/${key}`;
}

/** Localized message from a trilingual {en,hi,mr} error detail (or null). */
export function localizedDetail(e: unknown, lang: string): string | null {
  if (e instanceof ApiError && typeof e.detail === "object" && e.detail !== null) {
    const d = e.detail as Record<string, unknown>;
    const msg = d[lang.slice(0, 2)] ?? d.en;
    return typeof msg === "string" ? msg : null;
  }
  return null;
}
