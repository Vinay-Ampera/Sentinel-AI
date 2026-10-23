// Primary navigation entries. Only routes that exist are listed: nothing in the navbar may point
// at an unbuilt page. `auth: true` shows only when signed in, `guest: true` only when signed
// out, and `roles` only to those roles (a usability filter: the server still decides access).
export const NAV_ITEMS = [
  { to: '/', label: 'Home', end: true },
  { to: '/projects', label: 'Projects', auth: true },
  { to: '/approvals', label: 'Approvals', auth: true },
  { to: '/roadmap', label: 'Roadmap' },
  { to: '/admin', label: 'Admin', auth: true, roles: ['admin', 'super_admin'] },
  { to: '/request-access', label: 'Request access', guest: true },
]

export function visibleNavItems(user) {
  return NAV_ITEMS.filter((item) => {
    if (item.roles) return Boolean(user && item.roles.includes(user.role))
    if (item.auth) return Boolean(user)
    if (item.guest) return !user
    return true
  })
}
