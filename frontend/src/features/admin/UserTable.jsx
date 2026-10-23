import Button from '../../components/Button.jsx'
import DataTable from '../../components/DataTable.jsx'
import { EmptyState } from '../../components/states.jsx'
import { formatDateTime } from '../../lib/format.js'

export default function UserTable({ users, onEdit }) {
  return (
    <DataTable
      caption="User accounts"
      rows={users}
      getRowKey={(u) => u.id}
      empty={<EmptyState title="No users match" />}
      columns={[
        { key: 'who', header: 'User', render: (u) => <><strong>{u.display_name}</strong><br /><span className="muted">{u.email}</span></> },
        { key: 'role', header: 'Role', render: (u) => u.role.replace('_', ' ') },
        { key: 'active', header: 'Account', render: (u) => (u.is_active ? 'Active' : 'Disabled') },
        { key: 'login', header: 'Last sign-in', render: (u) => (u.last_login_at ? formatDateTime(u.last_login_at) : 'Never') },
        { key: 'edit', header: <span className="visually-hidden">Edit</span>, render: (u) => <Button size="sm" onClick={() => onEdit(u)} aria-label={`Edit ${u.display_name}`}>Edit</Button> },
      ]}
    />
  )
}
