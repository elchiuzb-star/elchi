/** Small data-loading hook for the v2 screens: one place for loading, error and refresh (no extra runtime dep). */
import { useCallback, useEffect, useRef, useState } from "react";

export type AsyncState<T> = {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => void;
  setData: (value: T | null) => void;
};

export function useAsync<T>(loader: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  const loaded = useRef(false);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(loader, deps);

  // A different subject starts from scratch; a refresh of the same one does not.
  useEffect(() => {
    loaded.current = false;
  }, [run]);

  useEffect(() => {
    let cancelled = false;
    // A refresh keeps the current data on screen. Flipping back to a spinner unmounts everything below, which
    // throws away what the user was doing there - a half-written form, or a card that just said "sent".
    setLoading(!loaded.current);
    setError(null);
    run()
      .then((value) => {
        if (cancelled) return;
        loaded.current = true;
        setData(value);
      })
      .catch((cause) => {
        if (!cancelled) setError(cause);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [run, nonce]);

  return { data, error, loading, reload: () => setNonce((value) => value + 1), setData };
}

/** Runs one command with its own busy/error state; the idempotency key is created by the caller per action. */
export function useCommand<Args extends unknown[], T>(command: (...args: Args) => Promise<T>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const run = useCallback(
    async (...args: Args): Promise<T | null> => {
      setBusy(true);
      setError(null);
      try {
        return await command(...args);
      } catch (cause) {
        setError(cause);
        return null;
      } finally {
        setBusy(false);
      }
    },
    [command],
  );

  return { run, busy, error, clearError: () => setError(null) };
}
