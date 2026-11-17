/** Node path.posix subset used only by original manifest-directory admission. */
export const posix = {
  isAbsolute: (path: string) => path.startsWith('/'),
  normalize(path: string): string {
    if (path === '') return '.'
    const absolute = path.startsWith('/'), trailing = path.endsWith('/'), parts: string[] = []
    for (const part of path.split('/')) {
      if (part === '' || part === '.') continue
      if (part === '..') {
        if (parts.length && parts.at(-1) !== '..') parts.pop()
        else if (!absolute) parts.push('..')
      } else parts.push(part)
    }
    let value = parts.join('/')
    if (!value && !absolute) value = '.'
    if (value && trailing) value += '/'
    return (absolute ? '/' : '') + value
  },
}
