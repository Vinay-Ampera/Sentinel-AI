// Sign-in, sign-up (which is the request-access page: there is no self-registration) and
// request-access use a quiet layout: a minimal top bar and no footer.
export const AUTH_PATHS = new Set(['/signin', '/request-access'])
export const isAuthPath = (pathname) => AUTH_PATHS.has(pathname)
