const ACCESS = "hogo_access";
const REFRESH = "hogo_refresh";

export const getAccess = () => localStorage.getItem(ACCESS);
export const setTokens = (a: string, r: string) => {
  localStorage.setItem(ACCESS, a);
  localStorage.setItem(REFRESH, r);
};
export const clearTokens = () => {
  localStorage.removeItem(ACCESS);
  localStorage.removeItem(REFRESH);
};

async function tryRefresh(): Promise<boolean> {
  const rt = localStorage.getItem(REFRESH);
  if (!rt) return false;
  const res = await fetch("/api/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: rt }),
  });
  if (!res.ok) return false;
  const data = await res.json();
  setTokens(data.access_token, data.refresh_token);
  return true;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

export async function api(path: string, opts: RequestInit = {}, retry = true): Promise<any> {
  const headers: Record<string, string> = { ...(opts.headers as any) };
  if (!(opts.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const token = getAccess();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`/api${path}`, { ...opts, headers });
  if (res.status === 401 && retry && (await tryRefresh())) return api(path, opts, false);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}
