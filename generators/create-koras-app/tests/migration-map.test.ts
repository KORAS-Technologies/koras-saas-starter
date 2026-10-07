import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import yaml from 'js-yaml'
import { normaliseSql, sha256, stripComments, type Rule } from './migration-map-support.js'

/**
 * docs/migration-map.yaml: the Starter's secure_files migrations (00039-00042) are the Docoris
 * ones (01016-01019) except for the differences the map names. The Docoris repository is not
 * available here, so the comparison is against the checksum of its normalised text recorded in
 * the map. With DOCORIS_REPO set (a maintainer's machine) the recorded checksums are also checked
 * against the real files.
 */

const REPO = join(__dirname, '..', '..', '..')
const MAP_TEXT = readFileSync(join(REPO, 'docs', 'migration-map.yaml'), 'utf8')
const MAP = yaml.load(MAP_TEXT) as {
  schema_version: number
  migrations: {
    starter: string
    docoris: string
    differences: Rule[]
    docoris_normalised_sha256: string
  }[]
}

const KNOWN_RULES: Rule[] = [
  'transaction-wrapper',
  'lock-timeout',
  'function-comment',
  'to-regclass-wrapper',
]

describe('docs/migration-map.yaml', () => {
  it('maps exactly 00039-00042 onto 01016-01019, in order', () => {
    expect(MAP.schema_version).toBe(1)
    expect(MAP.migrations.map((m) => m.starter.split('/').pop()!.slice(0, 5))).toEqual([
      '00039',
      '00040',
      '00041',
      '00042',
    ])
    expect(MAP.migrations.map((m) => m.docoris.split('/').pop()!.slice(0, 5))).toEqual([
      '01016',
      '01017',
      '01018',
      '01019',
    ])
  })

  it('names only documented differences, each explained in the map header', () => {
    for (const entry of MAP.migrations) {
      for (const rule of entry.differences) {
        expect(KNOWN_RULES, rule).toContain(rule)
        expect(MAP_TEXT, rule).toMatch(new RegExp(`^#   ${rule}\\s`, 'm'))
      }
    }
  })

  it.each(MAP.migrations.map((m) => [m.starter.split('/').pop()!, m] as const))(
    '%s is the Docoris SQL apart from the listed differences',
    (_name, entry) => {
      const file = join(REPO, entry.starter)
      expect(existsSync(file), file).toBe(true)
      const normalised = normaliseSql(readFileSync(file, 'utf8'), entry.differences)
      expect(sha256(normalised)).toBe(entry.docoris_normalised_sha256)
    },
  )

  it('would notice a changed constraint: the comparison is not vacuous', () => {
    const first = MAP.migrations[0]!
    const text = readFileSync(join(REPO, first.starter), 'utf8')
    const mutated = text.replace('check (scan_attempts >= 0)', 'check (scan_attempts >= 1)')
    expect(mutated).not.toBe(text)
    expect(sha256(normaliseSql(mutated, first.differences))).not.toBe(first.docoris_normalised_sha256)
    // And a stray comment or whitespace change is not a difference.
    const reformatted = text.replace('begin;', 'begin;   -- a comment\n\n')
    expect(sha256(normaliseSql(reformatted, first.differences))).toBe(first.docoris_normalised_sha256)
  })

  it('every migration sets a transaction-local lock timeout before touching `files`', () => {
    for (const entry of MAP.migrations) {
      const sql = stripComments(readFileSync(join(REPO, entry.starter), 'utf8'))
      expect(sql, entry.starter).toMatch(/\bbegin\s*;/i)
      expect(sql, entry.starter).toMatch(/\bcommit\s*;/i)
      expect(sql, entry.starter).toMatch(/set\s+local\s+lock_timeout\s*=\s*'5s'\s*;/i)
      // `set local` is only meaningful inside the transaction, so after `begin`.
      expect(sql.search(/\bbegin\s*;/i)).toBeLessThan(sql.search(/set\s+local\s+lock_timeout/i))
    }
  })

  it.runIf(Boolean(process.env.DOCORIS_REPO))(
    'the recorded checksums are those of the real Docoris files (maintainer check)',
    () => {
      for (const entry of MAP.migrations) {
        const text = readFileSync(join(process.env.DOCORIS_REPO!, entry.docoris), 'utf8')
        const rules = entry.differences.filter((r) => r !== 'to-regclass-wrapper')
        expect(sha256(normaliseSql(text, rules, false)), entry.docoris).toBe(
          entry.docoris_normalised_sha256,
        )
      }
    },
  )
})
