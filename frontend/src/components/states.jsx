import { describeError } from '../lib/errors.js'
import Button from './Button.jsx'
import './states.css'

export function Skeleton({ lines = 3 }) {
  return (
    <div className="skeleton" aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="skeleton-line" style={{ width: `${90 - ((i * 17) % 40)}%` }} />
      ))}
    </div>
  )
}

export function Loading({ label = 'Loading…', lines = 3 }) {
  return (
    <div className="state state-loading">
      <p role="status" className="state-label">{label}</p>
      <Skeleton lines={lines} />
    </div>
  )
}

export function EmptyState({ title, children, action }) {
  return (
    <div className="state state-empty">
      <p className="state-title">{title}</p>
      {children && <p className="state-body">{children}</p>}
      {action && <div className="state-action">{action}</div>}
    </div>
  )
}

// What the user can do about each kind of failure. Never shows stack traces or server internals.
export function ErrorState({ error, onRetry }) {
  const info = describeError(error)
  const retryable = info.kind === 'network' || info.kind === 'server' || info.kind === 'unknown' || info.kind === 'conflict'
  return (
    <div className="state state-error" role="alert">
      <p className="state-title">{info.title}</p>
      <p className="state-body">{info.message}</p>
      {onRetry && retryable && (
        <div className="state-action">
          <Button onClick={onRetry}>{info.kind === 'conflict' ? 'Reload' : 'Try again'}</Button>
        </div>
      )}
    </div>
  )
}

// Shown instead of content when the server says 403. The UI explains; the server decides.
export function PermissionDenied({ what = 'this', children }) {
  return (
    <div className="state state-denied" role="alert">
      <p className="state-title">You do not have access to {what}</p>
      <p className="state-body">{children || 'Your role or project membership does not allow this. Ask a project owner or an administrator if you think you should have access.'}</p>
    </div>
  )
}

// Wraps a useLoad state: loading, error (403 becomes PermissionDenied), empty, then content.
// `children` is called with the loaded data. `isEmpty` decides what "empty" means.
export function DataState({ state, onRetry, isEmpty, empty, loadingLabel, what, children }) {
  if (state.loading) return <Loading label={loadingLabel} />
  if (state.error) {
    if (state.error.status === 403) return <PermissionDenied what={what} />
    return <ErrorState error={state.error} onRetry={onRetry} />
  }
  const nothing = isEmpty ? isEmpty(state.data) : Array.isArray(state.data) && state.data.length === 0
  if (nothing) return empty
  return children(state.data)
}
