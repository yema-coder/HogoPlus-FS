import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/src/api/client";
import { storage } from "@/src/utils/storage";

interface CacheEnvelope<T> {
  t: number;
  data: T;
}

interface CachedFetchResult<T> {
  data: T | null;
  fetchedAt: number | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/** Cache-first data hook: renders cached data instantly, refreshes in background. */
export function useCachedFetch<T>(key: string, fetcher: () => Promise<T>): CachedFetchResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [fetchedAt, setFetchedAt] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const fresh = await fetcherRef.current();
      if (!mounted.current) return;
      setData(fresh);
      const now = Date.now();
      setFetchedAt(now);
      setLoading(false);
      await storage.setItem(`hogo.cache.${key}`, JSON.stringify({ t: now, data: fresh }));
    } catch (e) {
      if (!mounted.current) return;
      setLoading(false);
      setError(e instanceof ApiError && e.status === 0 ? "network" : "server");
    }
  }, [key]);

  useEffect(() => {
    mounted.current = true;
    void (async () => {
      const raw = await storage.getItem<string>(`hogo.cache.${key}`, "");
      if (raw && mounted.current) {
        try {
          const env = JSON.parse(raw) as CacheEnvelope<T>;
          setData(env.data);
          setFetchedAt(env.t);
          setLoading(false);
        } catch {
          // ignore bad cache
        }
      }
      await refresh();
    })();
    return () => {
      mounted.current = false;
    };
  }, [key, refresh]);

  return { data, fetchedAt, loading, error, refresh };
}
