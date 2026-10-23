import { useEffect } from 'react'

export const APP_NAME = 'Sentinel AI'

// Keeps the browser tab and screen-reader page title in step with the visible page title.
export function useDocumentTitle(title) {
  useEffect(() => {
    document.title = title ? `${title} · ${APP_NAME}` : APP_NAME
  }, [title])
}
