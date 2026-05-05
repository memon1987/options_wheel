import { useState, useEffect, useCallback, useRef } from 'react';

interface UseApiOptions {
  /** Auto-refresh interval in milliseconds. 0 = no auto-refresh. Default: 0 */
  refreshInterval?: number;
  /** Whether to fetch immediately on mount. Default: true */
  immediate?: boolean;
}

interface UseApiResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

const TIMEOUT_MS = 15_000;
const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 2_000;

async function fetchWithTimeout(url: string, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { signal: controller.signal });
    return response;
  } finally {
    clearTimeout(timer);
  }
}

async function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchWithRetry<T>(url: string): Promise<T> {
  let lastError: Error | null = null;

  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      const response = await fetchWithTimeout(url, TIMEOUT_MS);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      const data = await response.json();
      return data as T;
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));

      if (lastError.name === 'AbortError') {
        lastError = new Error(`Request timed out after ${TIMEOUT_MS / 1000}s`);
      }

      if (attempt < MAX_RETRIES) {
        await sleep(RETRY_DELAY_MS);
      }
    }
  }

  throw lastError ?? new Error('Fetch failed after retries');
}

export function useApi<T>(url: string | null, options: UseApiOptions = {}): UseApiResult<T> {
  const { refreshInterval = 0, immediate = true } = options;

  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(immediate && !!url);
  const [error, setError] = useState<string | null>(null);

  const mountedRef = useRef(true);
  const urlRef = useRef(url);
  urlRef.current = url;

  const fetchData = useCallback(async () => {
    if (!url) {
      // Skip mode — pages pass null to suspend a request that depends on
      // a value (e.g., a route param) that isn't available yet.
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);

    try {
      const result = await fetchWithRetry<T>(url);
      if (mountedRef.current && urlRef.current === url) {
        setData(result);
        setError(null);
      }
    } catch (err) {
      if (mountedRef.current && urlRef.current === url) {
        const message = err instanceof Error ? err.message : 'An unknown error occurred';
        setError(message);
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false);
      }
    }
  }, [url]);

  useEffect(() => {
    mountedRef.current = true;

    if (immediate && url) {
      fetchData();
    } else if (!url) {
      // Clear stale data when URL becomes null (e.g., navigating away from a symbol).
      setData(null);
      setLoading(false);
    }

    return () => {
      mountedRef.current = false;
    };
  }, [fetchData, immediate, url]);

  useEffect(() => {
    if (refreshInterval <= 0 || !url) return;

    const interval = setInterval(() => {
      if (mountedRef.current) {
        fetchData();
      }
    }, refreshInterval);

    return () => clearInterval(interval);
  }, [fetchData, refreshInterval, url]);

  return { data, loading, error, refetch: fetchData };
}
