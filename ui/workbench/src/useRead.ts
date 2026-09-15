import { useEffect, useRef, useState } from 'react';
import { reduceRead, visibleRead, type ResourceState } from './readState';

/** Explicit identity/revision reads only. No polling, automatic retry or global cache. */
export function useRead<T>(identity: string, revision: number | string, load: (signal: AbortSignal) => Promise<T>) {
  const loader = useRef(load);
  loader.current = load;
  const request = JSON.stringify([identity, revision]);
  const [state, setState] = useState<ResourceState<T>>({ identity: '', request: '', loading: false });
  useEffect(() => {
    const controller = new AbortController();
    const read = loader.current;
    setState(old => reduceRead(old, { type: 'start', identity, request }));
    if (identity) Promise.resolve().then(() => read(controller.signal)).then(data => {
      if (!controller.signal.aborted) setState(old => reduceRead(old, { type: 'success', request, data }));
    }).catch(error => {
      if (!controller.signal.aborted) setState(old => reduceRead(old, {
        type: 'failure', request, error: error instanceof Error ? error.message : String(error),
      }));
    });
    return () => controller.abort();
  }, [identity, request]);
  // Effects run after render; mask another context's data immediately.
  return visibleRead(state, identity, request);
}
