import Icon from './Icon.jsx'
import './Alert.css'

const ICONS = { danger: 'alert', warning: 'alert', success: 'check', info: 'info', neutral: 'info' }

// An in-page notice. Errors use role="alert" (announced at once); the others use role="status".
// Use it for form-level errors, honest limitations ("this does not run anything") and results.
export default function Alert({ tone = 'info', title, children }) {
  return (
    <div className={`alert alert-${tone}`} role={tone === 'danger' ? 'alert' : 'status'}>
      <Icon name={ICONS[tone] || 'info'} />
      <div className="alert-body">
        {title && <strong className="alert-title">{title}</strong>}
        {children && <div>{children}</div>}
      </div>
    </div>
  )
}
