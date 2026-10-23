import { useCallback, useState } from 'react'
import Button from '../components/Button.jsx'
import Card from '../components/Card.jsx'
import Field from '../components/Field.jsx'
import PageHeader from '../components/PageHeader.jsx'
import { DataState } from '../components/states.jsx'
import GlobalPolicies from '../features/admin/GlobalPolicies.jsx'
import UserDialog from '../features/admin/UserDialog.jsx'
import UserTable from '../features/admin/UserTable.jsx'
import { useApi } from '../hooks/useApi.js'
import { useLoad } from '../hooks/useLoad.js'
import { useToast } from '../hooks/useToast.js'
import './AdminPage.css'

// Administration: user accounts and organization policy. Shown to admins and super admins; the
// server decides what each may do (for example only a super admin manages privileged accounts).
export default function AdminPage() {
  const api = useApi()
  const { notify } = useToast()
  const [q, setQ] = useState('')
  const [search, setSearch] = useState('')
  const [dialog, setDialog] = useState(null) // { user } | null
  const [users, reload] = useLoad(useCallback(() => api.listUsers(search), [api, search]))

  async function save(body) {
    if (dialog.user) await api.updateUser(dialog.user.id, body)
    else await api.createUser(body)
    notify({ tone: 'success', title: dialog.user ? 'User updated' : 'User created' })
    setDialog(null)
    reload()
  }

  return (
    <>
      <PageHeader title="Administration" description="User accounts and organization-wide policy." />
      <Card title="Users" actions={<Button size="sm" variant="primary" onClick={() => setDialog({ user: null })}>New user</Button>}>
        <form className="admin-search" role="search" aria-label="Find a user" onSubmit={(e) => { e.preventDefault(); setSearch(q.trim()) }}>
          <Field label="Name or email" value={q} onChange={(e) => setQ(e.target.value)} />
          <Button type="submit">Search</Button>
        </form>
        <DataState state={users} onRetry={reload} what="user accounts" loadingLabel="Loading users…" isEmpty={() => false}>
          {(items) => <UserTable users={items} onEdit={(user) => setDialog({ user })} />}
        </DataState>
      </Card>
      <GlobalPolicies />
      {dialog && <UserDialog key={dialog.user ? dialog.user.id : 'new'} user={dialog.user} onClose={() => setDialog(null)} onSave={save} />}
    </>
  )
}
