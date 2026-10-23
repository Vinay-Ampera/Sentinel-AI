import { useId } from 'react'
import './DataTable.css'

// A responsive table: the table scrolls horizontally inside a labelled, keyboard-focusable
// region on narrow screens (so it is reachable without a mouse), with a visible cue.
// columns: [{ key, header, render?(row), align?: 'end' }].
export default function DataTable({ caption, columns, rows, getRowKey, empty }) {
  const captionId = useId()
  // The scroll region is named "<caption> table" so it never shares a name with a card or
  // section of the same title (landmarks on a page must be distinguishable).
  if (rows.length === 0 && empty) return empty
  return (
    <div className="table-scroll" role="region" aria-label={`${caption} table`} tabIndex={0}>
      <table className="data-table">
        <caption id={captionId} className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col" className={c.align === 'end' ? 'align-end' : undefined}>{c.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={getRowKey(row)}>
              {columns.map((c) => (
                <td key={c.key} className={c.align === 'end' ? 'align-end' : undefined}>
                  {c.render ? c.render(row) : row[c.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
