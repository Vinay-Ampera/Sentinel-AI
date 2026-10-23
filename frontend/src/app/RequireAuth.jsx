import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { Loading } from '../components/states.jsx'
import { useAuth } from '../hooks/useAuth.js'

// Route guard for the signed-in application. This is a usability redirect only: every API
// call is authorized by the server regardless of what the browser shows.
export default function RequireAuth() {
  const { user, checking } = useAuth()
  const location = useLocation()
  if (checking) return <Loading label="Checking session…" lines={2} />
  if (!user) {
    const next = `${location.pathname}${location.search}`
    return <Navigate to={`/signin?next=${encodeURIComponent(next)}`} replace />
  }
  return <Outlet />
}
