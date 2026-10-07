import { createHash } from 'node:crypto'

/**
 * Normalisation for comparing a Starter migration with the Docoris migration it was generalised
 * from (docs/migration-map.yaml). Two texts are "the same SQL" when, after these rules, they are
 * the same string. The rules are deliberately few and each documented difference is an explicit,
 * named rule listed per migration in the map: an undocumented difference fails the comparison.
 *
 * Always applied: line endings, `--` comments (SQL comments carry no semantics; the migrations'
 * strings never contain `--`), and whitespace runs.
 *
 * Applied only where the map names them:
 *   transaction-wrapper   `begin;` / `commit;` (the Starter wraps what Docoris ran bare, so that
 *                         the lock timeout below has a transaction to be local to)
 *   lock-timeout          `set local lock_timeout = '...';`
 *   function-comment      `comment on function ... is '...';` (its text names the origin)
 *   to-regclass-wrapper   the guard that skips the chunk delete in a product without `ai`
 */
export type Rule = 'transaction-wrapper' | 'lock-timeout' | 'function-comment' | 'to-regclass-wrapper'

const STRING = String.raw`'(?:[^']|'')*'`

export function stripComments(sql: string): string {
  return sql
    .split(String.fromCharCode(13))
    .join('')
    .split('\n')
    .map((line) => {
      // A `--` outside a string starts a comment. The migrations keep none inside strings, and
      // the check below makes a future one fail loudly rather than be mangled.
      const at = line.indexOf('--')
      if (at < 0) return line
      const before = line.slice(0, at)
      if ((before.match(/'/g) ?? []).length % 2 === 1) {
        throw new Error(`a "--" inside a string literal is not supported here: ${line}`)
      }
      return before
    })
    .join('\n')
}

export function normaliseSql(sql: string, rules: readonly Rule[], strict = true): string {
  let text = stripComments(sql)
  const apply = (rule: Rule, pattern: RegExp, replacement: string) => {
    if (!rules.includes(rule)) return
    pattern.lastIndex = 0
    if (!pattern.test(text)) {
      if (strict) throw new Error(`rule "${rule}" is listed but matches nothing`)
      return
    }
    pattern.lastIndex = 0
    text = text.replace(pattern, replacement)
  }
  apply('transaction-wrapper', /^\s*(?:begin|commit)\s*;\s*$/gim, '')
  apply('lock-timeout', /^\s*set\s+local\s+lock_timeout\s*=\s*'[^']*'\s*;\s*$/gim, '')
  apply(
    'function-comment',
    new RegExp(String.raw`comment\s+on\s+function\s+[\w.]+\(\)\s+is\s+(?:${STRING}\s*)+;`, 'gi'),
    '',
  )
  apply(
    'to-regclass-wrapper',
    /if\s+to_regclass\('public\.ai_knowledge_chunks'\)\s+is\s+not\s+null\s+then\s+([\s\S]*?;)\s*end\s+if\s*;/i,
    '$1',
  )
  return text.split(/\s+/).filter(Boolean).join(' ')
}

export const sha256 = (value: string): string => createHash('sha256').update(value).digest('hex')
