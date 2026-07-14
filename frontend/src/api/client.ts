import { Platform } from "react-native";

import { storage } from "@/src/utils/storage";

const BASE = (process.env.EXPO_PUBLIC_API_URL ?? "").replace(/\/+$/, "");
export const API_BASE = `${BASE}/api`;

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
  pdf: "application/pdf",
};

export async function uploadFile(
  uri: string,
  name: string,
  tokenOverride?: string,
): Promise<{ key: string; url: string }> {
  const ext = name.includes(".") ? name.split(".").pop()!.toLowerCase() : "jpg";
  const mime = MIME_BY_EXT[ext] ?? "image/jpeg";
  const fd = new FormData();
  if (Platform.OS === "web") {
    const blob = await (await fetch(uri)).blob();
    fd.append("file", blob, name);
  } else {
    fd.append("file", { uri, name, type: mime } as unknown as Blob);
  }
  return api<{ key: string; url: string }>("/files/upload", {
    method: "POST",
    formData: fd,
    tokenOverride,
  });
}

export function fileUrl(key: string): string {
  return `${API_BASE}/files/${key}`;
}
