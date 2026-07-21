import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

/** Prompt 18: cache-first data hook (mirrors the mobile SWR pattern).
 * Renders localStorage-cached data instantly, refreshes in the background. */
export function useCachedApi<T>(key: string, path: string) {
  const [data, setData] = useState<T | null>(() => {
    try {
      const raw = localStorage.getItem(`dash.cache.${key}`);
      return raw ? (JSON.parse(raw).data as T) : null;
    } catch {
      return null;
    }
  });
  const [loading, setLoading] = useState(data === null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const fresh = await api(path);
      setData(fresh);
      setError("");
      try {
        localStorage.setItem(`dash.cache.${key}`, JSON.stringify({ t: Date.now(), data: fresh }));
      } catch {
        /* storage full — stay memory-only */
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [key, path]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, loading, error, refresh };
}
