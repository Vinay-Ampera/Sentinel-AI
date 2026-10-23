import { useState } from 'react'

// Client-side paging for lists already loaded in memory.
export function usePagination(items, pageSize = 20) {
  const [requested, setPage] = useState(1)
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize))
  const page = Math.min(requested, pageCount) // stays valid if the list shrinks
  const start = (page - 1) * pageSize
  return { page, pageCount, setPage, pageItems: items.slice(start, start + pageSize), total: items.length, start }
}
