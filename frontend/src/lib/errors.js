// Turn an API failure into something safe and actionable to show. 401/403/404/409/422 get
// their own kind so pages can react (sign in again, explain missing permission, show field
// errors). Server error text is not echoed for 5xx: it may carry internals.

export function describeError(error) {
  const status = error && typeof error.status === 'number' ? error.status : null
  const message = error && error.message ? error.message : ''
  if (status === 0 || (error && error.code === 'network_error')) {
    return { kind: 'network', title: 'Could not reach the server', message: 'Check your connection and try again.' }
  }
  if (status === 401) {
    return { kind: 'auth', title: 'Your session has ended', message: 'Sign in again to continue.' }
  }
  if (status === 403) {
    return { kind: 'forbidden', title: 'You do not have permission', message: message || 'Your role or project access does not allow this.' }
  }
  if (status === 404) {
    return { kind: 'not_found', title: 'Not found', message: message || 'It may have been removed, or you may not have access.' }
  }
  if (status === 409) {
    return { kind: 'conflict', title: 'This changed elsewhere', message: message || 'Reload to see the latest state, then try again.' }
  }
  if (status === 422) {
    return { kind: 'validation', title: 'Check the details', message: message || 'Some values were not accepted.' }
  }
  if (status !== null && status >= 500) {
    return { kind: 'server', title: 'Something went wrong on the server', message: 'Try again shortly. Nothing was changed by this view.' }
  }
  return { kind: 'unknown', title: 'Something went wrong', message: message || 'Try again.' }
}

// Field-level validation messages from an ApiError's `details`, keyed by field name when the
// backend names one. Shape is tolerated loosely; unknown shapes yield no field errors.
export function fieldErrors(error) {
  const out = {}
  const details = error && Array.isArray(error.details) ? error.details : []
  for (const d of details) {
    const field = d && (d.field || (Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : null))
    const text = d && (d.message || d.msg)
    if (field && text && !out[field]) out[field] = String(text)
  }
  return out
}
