import { Outlet } from 'react-router-dom'
import PageHeader from '../components/PageHeader.jsx'
import { PermissionDenied } from '../components/states.jsx'
import { useAuth } from '../hooks/useAuth.js'

// Shows a section only to some roles. This is a usability check: the server refuses the same
// requests regardless, and anyone who reaches a page directly just sees the explanation.
export default function RequireRole({ roles, what }) {
  const { user } = useAuth()
  if (user && roles.includes(user.role)) return <Outlet />
  return (
    <>
      <PageHeader title="Not available to your role" />
      <PermissionDenied what={what} />
    </>
  )
}
