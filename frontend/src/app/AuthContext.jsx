import { useCallback, useEffect, useMemo, useState } from 'react'
import { AuthContext } from '../hooks/useAuth.js'
import { setUnauthorizedHandler } from '../services/api.js'

// Holds the signed-in user for the whole app. The server owns the session; this only mirrors
// what GET /auth/me returned. Role checks in the UI are for usability, never authorization.
// `expired` is true when a signed-in session ended on the server (a 401 from a protected call),
// so the sign-in page can say so instead of looking like a fresh visit.
export function AuthProvider({ api, children }) {
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(true)
  const [expired, setExpired] = useState(false)

  useEffect(() => {
    let live = true
    api
      .me()
      .then((u) => live && setUser(u))
      .catch(() => {}) // not signed in (or server unreachable): show the sign-in form
      .finally(() => live && setChecking(false))
    return () => {
      live = false
    }
  }, [api])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser((current) => {
        if (current) setExpired(true)
        return null
      })
    })
    return () => setUnauthorizedHandler(null)
  }, [])

  const signedIn = useCallback((u) => {
    setExpired(false)
    setUser(u)
  }, [])

  const signOut = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setExpired(false)
      setUser(null)
    }
  }, [api])

  const value = useMemo(() => ({ user, checking, expired, signedIn, signOut }), [user, checking, expired, signedIn, signOut])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
