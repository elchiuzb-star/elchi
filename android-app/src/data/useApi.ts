import { useCallback, useEffect, useRef, useState } from "react";
import { getUzbekErrorMessage } from "../utils/errors";

export type AsyncState<T> = {
  data: T | null;
  loading: boolean;
  error: string | null;
  /** Re-run the loader. Returns a promise that settles when the fetch finishes,
   *  so callers (e.g. pull-to-refresh) can await it. */
  reload: () => Promise<void>;
};

/**
 * Run an async loader on mount (and whenever `deps` change) and expose
 * { data, loading, error, reload }. Safe against unmounted updates.
 */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  // Keep the latest loader without making `run` change identity every render,
  // so effects/callbacks depending on `run` stay stable.
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback(() => {
    setLoading(true);
    setError(null);
    return loaderRef.current()
      .then((result) => {
        if (mounted.current) setData(result);
      })
      .catch((err) => {
        if (mounted.current) {
          setError(getUzbekErrorMessage(err));
          setData(null);
        }
      })
      .finally(() => {
        if (mounted.current) setLoading(false);
      });
  }, []);

  useEffect(() => {
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps]);

  return { data, loading, error, reload: run };
}
