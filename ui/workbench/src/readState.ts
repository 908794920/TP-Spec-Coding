import type { ReadState } from './types';

export interface ResourceState<T> extends ReadState<T> {
  identity: string;
  request: string;
}
export type ReadAction<T> =
  | { type: 'start'; identity: string; request: string }
  | { type: 'success'; request: string; data: T }
  | { type: 'failure'; request: string; error: string };

/** Request identity, not response arrival order, owns the visible result. */
export function reduceRead<T>(old: ResourceState<T>, action: ReadAction<T>): ResourceState<T> {
  if (action.type === 'start') return {
    identity: action.identity, request: action.request, loading: !!action.identity,
    data: action.identity === old.identity ? old.data : undefined,
  };
  if (action.request !== old.request) return old;
  return action.type === 'success'
    ? { ...old, data: action.data, loading: false, error: undefined }
    : { ...old, loading: false, error: action.error };
}

export function visibleRead<T>(state: ResourceState<T>, identity: string, request: string): ReadState<T> {
  if (state.identity !== identity) return { loading: !!identity };
  return state.request === request ? state : { data: state.data, loading: !!identity };
}
