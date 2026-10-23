import { useId } from 'react'
import './Card.css'

export default function Card({ as: Tag = 'section', title, headingLevel = 2, actions, children, className }) {
  const titleId = useId()
  const Heading = `h${headingLevel}`
  return (
    <Tag className={['card', className].filter(Boolean).join(' ')} aria-labelledby={title ? titleId : undefined}>
      {(title || actions) && (
        <div className="card-head">
          {title && <Heading id={titleId} className="card-title">{title}</Heading>}
          {actions && <div className="card-actions">{actions}</div>}
        </div>
      )}
      {children}
    </Tag>
  )
}

// A compact summary figure for report pages: label, value, optional hint.
export function Metric({ label, value, hint }) {
  return (
    <div className="metric">
      <dt className="metric-label">{label}</dt>
      <dd className="metric-value">{value}</dd>
      {hint && <dd className="metric-hint">{hint}</dd>}
    </div>
  )
}

export function MetricGrid({ children, label }) {
  return (
    <dl className="metric-grid" aria-label={label}>
      {children}
    </dl>
  )
}

// A restrained progress bar. Pass value=null for "in progress, amount unknown".
export function ProgressBar({ value, max = 100, label }) {
  const known = typeof value === 'number'
  const pct = known ? Math.max(0, Math.min(100, (value / max) * 100)) : null
  return (
    <div
      className="progress-bar"
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={known ? value : undefined}
      aria-valuetext={known ? `${Math.round(pct)}%` : 'In progress'}
    >
      <div className={known ? 'progress-fill' : 'progress-fill progress-indeterminate'} style={known ? { width: `${pct}%` } : undefined} />
    </div>
  )
}
