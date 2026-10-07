import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import {
  BaselineUsageError,
  checkBaseline,
  exitCodeFor,
  formatBaselineReport,
  readRecordedBaseline,
} from '../src/baseline/check.js'

/**
 * Framework baseline drift, against a real throwaway Starter repository.
 *
 * The git history is built here rather than stubbed, because the claim under
 * test is what git says about ancestry. Each product is a directory holding
 * only a .koras/project.yaml.
 */

const root = mkdtempSync(join(tmpdir(), 'koras-baseline-'))
const starter = join(root, 'starter')
const sha: Record<string, string> = {}

function git(...args: string[]): string {
  const r = spawnSync('git', ['-C', starter, ...args], { encoding: 'utf8' })
  if (r.status !== 0) throw new Error(`git ${args.join(' ')}: ${r.stderr}`)
  return r.stdout.trim()
}

function commit(name: string, file: string): void {
  mkdirSync(join(starter, file, '..'), { recursive: true })
  writeFileSync(join(starter, file), name)
  git('add', '-A')
  git('-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false', 'commit', '-m', name)
  sha[name] = git('rev-parse', 'HEAD')
}

function setAccepted(value: string): void {
  writeFileSync(join(starter, 'docs/framework-baseline.yaml'), `schema_version: 1\naccepted_baseline: ${value}\n`)
}

function product(name: string, framework: string): string {
  const dir = join(root, name)
  mkdirSync(join(dir, '.koras'), { recursive: true })
  writeFileSync(join(dir, '.koras/project.yaml'), `schema_version: 1\nproject:\n  profile: product\n${framework}`)
  return dir
}

const withBaseline = (s: string): string => `framework:\n  source_baseline: ${s}\n`

beforeAll(() => {
  mkdirSync(starter, { recursive: true })
  spawnSync('git', ['-C', starter, 'init', '-q', '-b', 'main'])
  commit('c1', 'README.md')
  commit('c2', 'profiles/product/template/a.txt')
  commit('c3', 'docs/note.md') // not framework-relevant
  commit('c4', 'profiles/_shared/template/b.txt')
  // A branch that is neither behind nor ahead of main.
  git('checkout', '-q', '-b', 'side', sha.c1)
  commit('s1', 'side.txt')
  git('checkout', '-q', 'main')
  mkdirSync(join(starter, 'docs'), { recursive: true })
  setAccepted(sha.c4)
})

afterAll(() => rmSync(root, { recursive: true, force: true }))

describe('framework baseline drift', () => {
  it('is current when the product records the accepted baseline', () => {
    const r = checkBaseline(starter, product('cur', withBaseline(sha.c4)))
    expect(r.status).toBe('current')
  })

  it('is behind, with the count and only framework-relevant paths', () => {
    const r = checkBaseline(starter, product('behind', withBaseline(sha.c1)))
    expect(r.status).toBe('behind')
    expect(r.commits).toBe(3)
    expect(r.changedPaths).toEqual(['profiles/_shared/template/b.txt', 'profiles/product/template/a.txt'])
    expect(formatBaselineReport(r)).toContain('behind by 3 commit(s)')
  })

  it('is unknown when no baseline is recorded, and never throws for it', () => {
    const r = checkBaseline(starter, product('none', ''))
    expect(r.status).toBe('unknown')
    expect(r.reason).toMatch(/no framework\.source_baseline/)
  })

  it('is unknown when the recorded commit is not in the Starter checkout', () => {
    const r = checkBaseline(starter, product('gone', withBaseline('0'.repeat(39) + 'a')))
    expect(r.status).toBe('unknown')
    expect(r.reason).toMatch(/not in the Starter checkout/)
  })

  it('is ahead when the product is past the accepted baseline', () => {
    setAccepted(sha.c2)
    try {
      const r = checkBaseline(starter, product('ahead', withBaseline(sha.c4)))
      expect(r.status).toBe('ahead')
      expect(r.commits).toBe(2)
    } finally {
      setAccepted(sha.c4)
    }
  })

  it('is diverged when neither baseline is an ancestor of the other', () => {
    const r = checkBaseline(starter, product('div', withBaseline(sha.s1)))
    expect(r.status).toBe('diverged')
  })

  it('accepts an abbreviated SHA', () => {
    const r = checkBaseline(starter, product('short', withBaseline(sha.c4.slice(0, 10))))
    expect(r.status).toBe('current')
  })

  it('preserves nothing and writes nothing: the product tree is only read', () => {
    const dir = product('ro', withBaseline(sha.c1))
    const before = readRecordedBaseline(dir)
    checkBaseline(starter, dir)
    expect(readRecordedBaseline(dir)).toEqual(before)
  })

  it('reports a malformed accepted baseline or a missing manifest as a usage error', () => {
    setAccepted('not-a-sha')
    try {
      expect(() => checkBaseline(starter, product('x', ''))).toThrow(BaselineUsageError)
    } finally {
      setAccepted(sha.c4)
    }
    expect(() => checkBaseline(starter, join(root, 'no-such-product'))).toThrow(BaselineUsageError)
  })
})

describe('exit codes', () => {
  const report = (status: 'current' | 'behind' | 'ahead' | 'diverged' | 'unknown') => ({ status, accepted: 'a' })

  it('never fails by default, whatever the status', () => {
    for (const s of ['current', 'behind', 'ahead', 'diverged', 'unknown'] as const) {
      expect(exitCodeFor(report(s), false), s).toBe(0)
    }
  })

  it('fails under --strict unless the product is current or ahead', () => {
    expect(exitCodeFor(report('current'), true)).toBe(0)
    expect(exitCodeFor(report('ahead'), true)).toBe(0)
    for (const s of ['behind', 'diverged', 'unknown'] as const) {
      expect(exitCodeFor(report(s), true), s).toBe(1)
    }
  })
})