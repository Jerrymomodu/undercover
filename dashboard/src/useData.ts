import { useCallback, useEffect, useState } from "react";

/** Load data on mount, and again every refreshMs if it is given. */
export function useData<T>(load: () => Promise<T>, refreshMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(
    () =>
      load().then(
        (value) => {
          setData(value);
          setError(null);
        },
        (reason: unknown) => {
          setError(reason instanceof Error ? reason.message : String(reason));
        },
      ),
    [load],
  );

  useEffect(() => {
    void refresh();
    if (refreshMs === undefined) return;
    const timer = setInterval(() => void refresh(), refreshMs);
    return () => {
      clearInterval(timer);
    };
  }, [refresh, refreshMs]);

  return { data, error, refresh };
}
