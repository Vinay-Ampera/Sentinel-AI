import { Link } from 'react-router-dom'
import { useDocumentTitle } from '../hooks/useDocumentTitle.js'
import './PageHeader.css'

// The consistent top of every page: breadcrumbs (when useful), the one <h1>, a short
// description, metadata (status, last updated) and the page's primary actions.
// breadcrumbs: [{ to?, label }]; the last item is the current page.
export default function PageHeader({ title, description, breadcrumbs, meta, actions }) {
  useDocumentTitle(title)
  return (
    <header className="page-header">
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="breadcrumbs">
          <ol>
            {breadcrumbs.map((crumb, i) => {
              const last = i === breadcrumbs.length - 1
              return (
                <li key={`${crumb.label}-${i}`}>
                  {crumb.to && !last ? <Link to={crumb.to}>{crumb.label}</Link> : <span aria-current={last ? 'page' : undefined}>{crumb.label}</span>}
                </li>
              )
            })}
          </ol>
        </nav>
      )}
      <div className="page-header-row">
        <div className="page-header-main">
          <h1>{title}</h1>
          {description && <p className="page-description">{description}</p>}
          {meta && <div className="page-meta">{meta}</div>}
        </div>
        {actions && <div className="page-actions">{actions}</div>}
      </div>
    </header>
  )
}
