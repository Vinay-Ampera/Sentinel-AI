import { useEffect, useState } from 'react'
import { api as defaultApi } from '../services/api.js'
import SignIn from '../features/auth/SignIn.jsx'
import PlansPage from '../features/plans/PlansPage.jsx'

export default function App({ api = defaultApi }) {
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(true)

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

  async function signOut() {
    try {
      await api.logout()
    } finally {
      setUser(null)
    }
  }

  return (
    <main>
      <h1>Sentinel AI</h1>
      {checking && <p role="status">Checking session…</p>}
      {!checking && !user && <SignIn api={api} onSignedIn={setUser} />}
      {user && (
        <>
          <p>
            Signed in as {user.display_name} ({user.role.replace('_', ' ')}){' '}
            <button type="button" onClick={signOut}>Sign out</button>
          </p>
          <PlansPage api={api} user={user} />
        </>
      )}
    </main>
  )
}
