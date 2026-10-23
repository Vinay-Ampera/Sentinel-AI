import { describeError } from '../../lib/errors.js'

export function signInMessage(error) {
  if (error && error.status === 401) return 'The email or password is incorrect.'
  if (error && error.status === 429) return 'Too many sign-in attempts. Wait a moment and try again.'
  return describeError(error).message
}
