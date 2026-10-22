export type RequestState<T> =
  | { status: 'idle' }
  | { status: 'submitting' }
  | { status: 'success'; data: T }
  | { status: 'error'; message: string };
