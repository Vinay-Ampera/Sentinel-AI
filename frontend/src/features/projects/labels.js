import { formatBytes } from '../../lib/format.js'

// Wording for project concepts. Access levels and source rules mirror the backend (the server
// enforces them; these labels only explain).
export const APPLICATION_TYPES = {
  web_app: 'Web application',
  rest_api: 'REST API',
  ai_app: 'AI application',
}

export const ACCESS_LEVELS = {
  read: { label: 'Read', note: 'View the project, plans, runs and findings' },
  run: { label: 'Run', note: 'Also analyze, plan and run checks' },
  manage: { label: 'Manage', note: 'Also manage sources, members and approvals' },
}

export const SOURCE_TYPES = {
  zip_upload: 'ZIP upload',
  git_repository: 'Git repository',
  localhost_url: 'Localhost URL',
  remote_url: 'Remote URL',
}

// Only ZIP uploads can be analysed today; the other kinds are recorded as descriptors and
// nothing is fetched, cloned or contacted.
export const ANALYSABLE_SOURCE = new Set(['zip_upload'])

export const REMOTE_ENVIRONMENTS = ['dev', 'staging']

export const typeLabel = (t) => APPLICATION_TYPES[t] || t
export const accessLabel = (a) => (ACCESS_LEVELS[a] ? ACCESS_LEVELS[a].label : a || 'Unknown')
export const sourceTypeLabel = (t) => SOURCE_TYPES[t] || t

export function sourceDetail(s) {
  if (s.source_type === 'zip_upload') return formatBytes(s.size_bytes)
  if (s.source_type === 'git_repository') return `${s.git_url}${s.git_ref ? ` @ ${s.git_ref}` : ''}`
  return `${s.target_url}${s.environment ? ` (${s.environment})` : ''}`
}
