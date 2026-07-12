import { useCallback, useEffect, useRef, useState } from "react";
import { getUzbekErrorMessage } from "../utils/errors";

export type AsyncState<T> = {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
};

/**
 * Run an async loader on mount (and whenever `deps` change) and expose
 * { data, loading, error, reload }. Safe against unmounted updates.
 */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    setLoading(true);
    setError(null);
    loader()
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((value) => value + 1), []);
  return { data, loading, error, reload };
}
