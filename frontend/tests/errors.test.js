import { describe, expect, it } from 'vitest'
import { describeError, fieldErrors } from '../src/lib/errors.js'
import { ApiError } from '../src/services/api.js'

describe('describeError', () => {
  it.each([
    [new ApiError(0, 'network_error', 'x'), 'network'],
    [new ApiError(401, 'unauthenticated', 'x'), 'auth'],
    [new ApiError(403, 'forbidden', 'Not allowed'), 'forbidden'],
    [new ApiError(404, 'not_found', 'x'), 'not_found'],
    [new ApiError(409, 'conflict', 'x'), 'conflict'],
    [new ApiError(422, 'validation_failed', 'x'), 'validation'],
    [new ApiError(500, 'error', 'x'), 'server'],
    [new Error('boom'), 'unknown'],
  ])('maps %# to %s', (error, kind) => {
    expect(describeError(error).kind).toBe(kind)
  })

  it('does not echo server text for 5xx errors', () => {
    const info = describeError(new ApiError(500, 'error', 'Traceback: secret internals'))
    expect(JSON.stringify(info)).not.toMatch(/secret internals/)
  })

  it('extracts field errors from either detail shape and ignores unknown shapes', () => {
    const e = new ApiError(422, 'validation_failed', 'x', [{ field: 'email', message: 'Invalid email' }, { loc: ['body', 'name'], msg: 'Required' }, 'odd'])
    expect(fieldErrors(e)).toEqual({ email: 'Invalid email', name: 'Required' })
    expect(fieldErrors(new Error('x'))).toEqual({})
  })
})
