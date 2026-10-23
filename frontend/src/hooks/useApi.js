import { createContext, useContext } from 'react'

// The API client is provided once by <App> so pages do not thread it through props; tests
// provide a fake.
export const ApiContext = createContext(null)

export function useApi() {
  const value = useContext(ApiContext)
  if (!value) throw new Error('useApi must be used inside <App>')
  return value
}
