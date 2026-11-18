export function authReturnPath(value: string | null): string {
  if (!value?.startsWith('/') || value.startsWith('//') || /[\\\s]/u.test(value)) return '/projects'
  const url = new URL(value, window.location.origin)
  if (url.origin !== window.location.origin || url.pathname.startsWith('//') || /^\/(login|bootstrap|set-password)\/?$/iu.test(url.pathname)) return '/projects'
  return `${url.pathname}${url.search}${url.hash}`
}
