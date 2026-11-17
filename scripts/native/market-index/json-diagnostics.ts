/** Pinned Node 24.9 / V8 13.6 JSON syntax diagnostics over UTF-16 positions.
 * Grammar recognition only: valid values are still parsed by the shipped VM.
 * Diagnostic selection/context follows V8; see json-diagnostics-input.json and
 * V8-LICENSE for its immutable source references and attribution.
 */
export function jsonSyntaxMessage(text: string): string | undefined {
  let position = 0
  const length = text.length
  const digit = (c: string) => c >= '0' && c <= '9'
  const whitespace = () => { while (' \t\r\n'.includes(text[position] ?? '\0')) position++ }
  const located = (message: string, suffix = ' in JSON') => {
    let line = 1, start = 0
    for (let at = 0; at < position; at++) {
      if (text[at] === '\r' && at < position - 1 && text[at + 1] === '\n') at++
      if (text[at] === '\r' || text[at] === '\n') { line++; start = at + 1 }
    }
    return `${message}${suffix} at position ${position} (line ${line} column ${position - start + 1})`
  }
  const fail = (message?: string): never => {
    if (message !== undefined) throw located(message)
    if (position === length) throw 'Unexpected end of JSON input'
    const token = text[position]
    if (digit(token) || token === '-') throw located('Unexpected number')
    if (token === '"') throw located('Unexpected string')
    if (['[object Object]', 'undefined', 'Infinity', 'NaN'].includes(text)) throw `"${text}" is not valid JSON`
    let context = `"${text}"`
    if (length >= 21) {
      context = position < 10 ? `"${text.slice(0, position + 10)}"...`
        : position < length - 10 ? `..."${text.slice(position - 10, position + 10)}"...`
        : `..."${text.slice(position - 10)}"`
    }
    throw `Unexpected token '${token}', ${context} is not valid JSON`
  }
  const string = () => {
    position++
    while (position < length) {
      const c = text[position]
      if (c === '"') { position++; return }
      if (c.charCodeAt(0) < 32) fail('Bad control character in string literal')
      if (c !== '\\') { position++; continue }
      position++
      if (position === length || text.charCodeAt(position) > 255) fail()
      const escaped = text[position]
      if (escaped === 'u') {
        for (let count = 0; count < 4; count++) {
          position++
          if (!/[0-9a-fA-F]/.test(text[position] ?? '')) fail('Bad Unicode escape')
        }
      } else if (!'"\\/bfnrt'.includes(escaped)) fail('Bad escaped character')
      position++
    }
    fail('Unterminated string')
  }
  const number = () => {
    if (text[position] === '-') {
      position++
      if (!digit(text[position])) fail('No number after minus sign')
    }
    if (text[position] === '0') {
      position++
      if (digit(text[position])) throw located('Unexpected number')
    } else while (digit(text[position])) position++
    if (text[position] === '.') {
      position++
      if (!digit(text[position])) fail('Unterminated fractional number')
      while (digit(text[position])) position++
    }
    if (text[position] === 'e' || text[position] === 'E') {
      position++
      if (text[position] === '+' || text[position] === '-') position++
      if (!digit(text[position])) fail('Exponent part is missing a number')
      while (digit(text[position])) position++
    }
  }
  try {
    const todo = ['value']
    while (todo.length) {
      const mode = todo.pop()
      whitespace()
      const c = text[position]
      if (mode === 'value') {
        if (c === '{') { position++; todo.push('object-first') }
        else if (c === '[') { position++; todo.push('array-first') }
        else if (c === '"') string()
        else if (c === '-' || digit(c)) number()
        else if (c === 't' || c === 'f' || c === 'n') {
          const literal = c === 't' ? 'true' : c === 'f' ? 'false' : 'null'
          for (const expected of literal) {
            if (text[position] !== expected) fail()
            position++
          }
        } else fail()
      } else if (mode === 'object-first' || mode === 'object-next') {
        if (mode === 'object-first' && c === '}') { position++; continue }
        if (c !== '"') fail(mode === 'object-first' ? "Expected property name or '}'" : 'Expected double-quoted property name')
        string(); whitespace()
        if (text[position] !== ':') fail("Expected ':' after property name")
        position++; todo.push('object-tail', 'value')
      } else if (mode === 'array-first') {
        if (c === ']') position++
        else todo.push('array-tail', 'value')
      } else {
        const object = mode === 'object-tail'
        if (c === (object ? '}' : ']')) position++
        else if (c === ',') {
          position++
          if (object) todo.push('object-next')
          else todo.push('array-tail', 'value')
        } else fail(object ? "Expected ',' or '}' after property value" : "Expected ',' or ']' after array element")
      }
    }
    whitespace()
    if (position !== length) throw located('Unexpected non-whitespace character after JSON', '')
  } catch (error) {
    if (typeof error === 'string') return error
    throw error
  }
  return undefined
}
