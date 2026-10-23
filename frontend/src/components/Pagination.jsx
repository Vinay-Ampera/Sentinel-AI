import Button from './Button.jsx'
import './Pagination.css'

export default function Pagination({ page, pageCount, onPageChange, label = 'Pagination' }) {
  if (pageCount <= 1) return null
  return (
    <nav className="pagination" aria-label={label}>
      <Button size="sm" onClick={() => onPageChange(page - 1)} disabled={page <= 1}>Previous</Button>
      <span aria-current="page" className="pagination-status">Page {page} of {pageCount}</span>
      <Button size="sm" onClick={() => onPageChange(page + 1)} disabled={page >= pageCount}>Next</Button>
    </nav>
  )
}
