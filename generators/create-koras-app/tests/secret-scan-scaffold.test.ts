import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { generateKeyPairSync } from 'node:crypto'
import { existsSync, readFileSync, rmSync } from 'node:fs'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import {
  resolveSelections,
  applyComponentOverrides,
  validateSelections,
} from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'
import { writeFiles } from '../src/generation/writer.js'

/**
 * What a generated project refuses to commit, and what its secret scan can see.
 *
 * Asserted against a rendered project rather than the template text, and asked
 * of git rather than read from .gitignore, because what matters is the decision
 * git makes about a path in the project the generator actually wrote -- a rule
 * can be present and overridden by a later negation, or anchored somewhere the
 * file never lands.
 *
 * The scan half exists because the allowlists used to be wide enough to hide
 * real keys: unanchored `tests/.*` paths applying to every rule. Narrowing them
 * is only worth something if the narrowing cannot quietly come back.
 */

const OUT = join(tmpdir(), `koras-secretscan-${process.pid}-${Date.now()}`)

afterAll(() => {
  if (existsSync(OUT)) rmSync(OUT, { recursive: true, force: true })
})

async function generate(profile: ProfileName, slug: string) {
  const { manifest, defaults } = loadProfile(profile)
  const selections = resolveSelections(manifest, defaults)
  applyComponentOverrides(manifest, selections, {})
  validateSelections(manifest, selections)
  const ctx = buildContext({
    projectName: slug,
    projectSlug: slug,
    profile,
    manifest,
    defaults,
    selections,
    outputDir: OUT,
    dryRun: false,
    provision: false,
  })
  const { fileList } = await writeFiles(ctx, renderTemplate(ctx))
  const root = join(OUT, slug)
  const init = spawnSync('git', ['init', '-q'], { cwd: root })
  if (init.status !== 0) throw new Error(`git init failed: ${init.stderr}`)
  return { root, fileList, read: (rel: string) => readFileSync(join(root, rel), 'utf8') }
}

/** The paths git would refuse to stage, out of `candidates`. */
function ignored(root: string, candidates: string[]): string[] {
  const result = spawnSync('git', ['check-ignore', '--stdin'], {
    cwd: root,
    input: candidates.join('\n'),
    encoding: 'utf8',
  })
  // Exit 1 means "none of them": a valid answer, not a failure.
  if (result.status !== 0 && result.status !== 1) throw new Error(result.stderr)
  return result.stdout.split('\n').filter(Boolean)
}

interface TomlSection {
  header: string
  body: string
}

/**
 * Split a gitleaks config on its table headers. Enough structure to assert
 * on, without a TOML dependency the generator does not otherwise need.
 */
function sections(toml: string): TomlSection[] {
  const out: TomlSection[] = []
  const lines = toml.replace(/\r\n/g, '\n').split('\n')
  let current: TomlSection | null = null
  let inString = false
  for (const line of lines) {
    if (!inString && /^\[\[?[a-z.]+\]\]?\s*$/.test(line)) {
      current = { header: line.trim(), body: '' }
      out.push(current)
      continue
    }
    // A multi-line description may contain anything, including a line that
    // looks like a header; track the triple quotes so it is not mistaken.
    if ((line.match(/"""/g) ?? []).length % 2 === 1) inString = !inString
    if (current) current.body += `${line}\n`
  }
  return out
}

function pathPatterns(section: TomlSection): string[] {
  const block = /paths\s*=\s*\[([\s\S]*?)\]/.exec(section.body)
  if (!block) return []
  return [...block[1].matchAll(/'''(.*?)'''/g)].map((m) => m[1])
}

/** The rule id each `[[rules.allowlists]]` section belongs to. */
function ruleAllowlists(all: TomlSection[]): Array<{ rule: string; section: TomlSection }> {
  const out: Array<{ rule: string; section: TomlSection }> = []
  let rule = ''
  for (const s of all) {
    if (s.header === '[[rules]]') rule = /id\s*=\s*"([^"]+)"/.exec(s.body)?.[1] ?? ''
    if (s.header === '[[rules.allowlists]]') out.push({ rule, section: s })
  }
  return out
}

describe.each(['product', 'control-plane'] as const)('%s: what cannot be committed', (profile) => {
  let gen: Awaited<ReturnType<typeof generate>>

  beforeAll(async () => {
    gen = await generate(profile, `${profile}-ignores`)
  })

  it.each([
    // Per-user Claude Code permissions, at the root and in any package.
    '.claude/settings.local.json',
    'apps/web/.claude/settings.local.json',
    // Where the harnesses write their keys.
    '.e2e/identity.json',
    'e2e/support/key.json',
    // Key material by shape, wherever it lands -- tests/ included, since no
    // fixture is a key file.
    'tests/fixtures/signing.pem',
    'services/api/server.key',
    'tests/fixtures/rsa.jwk',
    'zitadel-sa-key.json',
    'local/certs/client.p12',
    'certs/client.pfx',
  ])('ignores %s', (path) => {
    expect(ignored(gen.root, [path])).toEqual([path])
  })

  it.each(['.claude/settings.json', 'local/config/.env.local.example', '.gitleaks.toml'])(
    'still commits %s',
    (path) => {
      // A rule that also swallowed shared configuration would be deleted, and
      // then it would protect nothing.
      expect(ignored(gen.root, [path])).toEqual([])
    },
  )

  it('ignores none of the files the generator itself writes', () => {
    // The key-shape rules are deliberately broad. This is the check that they
    // are not broad enough to silently drop part of the project from its own
    // first commit.
    expect(ignored(gen.root, gen.fileList)).toEqual([])
  })
})

describe.each(['product', 'control-plane'] as const)('%s: what the secret scan sees', (profile) => {
  let all: TomlSection[]

  beforeAll(async () => {
    const gen = await generate(profile, `${profile}-scan`)
    all = sections(gen.read('.gitleaks.toml'))
  })

  it('anchors every allowlisted path', () => {
    // Unanchored, `tests/.*` also matches `docs/features/.../tests/...`. That
    // is how 72 findings in committed trace archives went unexamined.
    const unanchored = all.flatMap(pathPatterns).filter((p) => !p.startsWith('^'))
    expect(unanchored).toEqual([])
  })

  it('allowlists tests only for the generic rules', () => {
    // A path allowlist that applies to every rule hides a real private key or
    // provider token committed under tests/. The fixtures there trip only the
    // generic rules, so only those are allowlisted.
    const testPaths = (s: TomlSection) =>
      pathPatterns(s).some((p) => p.startsWith('^tests/') || p.startsWith('^e2e/'))

    const global = all.filter((s) => s.header === '[[allowlists]]' && testPaths(s))
    expect(global).toEqual([])

    const scoped = ruleAllowlists(all)
      .filter(({ section }) => testPaths(section))
      .map(({ rule }) => rule)
      .sort()
    expect(scoped).toEqual(['generic-api-key', 'jwt'])
  })

  it('does not rely on targetRules in a global allowlist', () => {
    // Measured on gitleaks 8.28.0: `targetRules` naming a rule from the
    // extended default set makes the allowlist suppress nothing. Relying on it
    // fails open the other way -- the allowlist looks scoped and does nothing.
    const global = all.filter((s) => s.header === '[[allowlists]]')
    expect(global.filter((s) => /targetRules/.test(s.body))).toEqual([])
  })

  it('detects a private JWK, and only the private half', () => {
    // The default rules read a JWK as structure. This is the rule that does
    // not, exercised against a key generated now -- not a committed fixture,
    // which would itself be the thing the rule exists to stop.
    const rule = all.find((s) => s.header === '[[rules]]' && /id\s*=\s*"private-jwk"/.test(s.body))
    expect(rule).toBeDefined()
    const source = /regex\s*=\s*'''(.*?)'''/.exec(rule!.body)?.[1]
    expect(source).toBeDefined()
    const pattern = new RegExp(source!)

    const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 })
    expect(pattern.test(JSON.stringify(privateKey.export({ format: 'jwk' })))).toBe(true)
    expect(pattern.test(JSON.stringify(publicKey.export({ format: 'jwk' })))).toBe(false)

    const ec = generateKeyPairSync('ec', { namedCurve: 'P-256' })
    expect(pattern.test(JSON.stringify(ec.privateKey.export({ format: 'jwk' })))).toBe(true)
    expect(pattern.test(JSON.stringify(ec.publicKey.export({ format: 'jwk' })))).toBe(false)
  })

  it('does not exempt local scripts', () => {
    // `local/scripts/.*` used to be allowlisted wholesale. Nothing there needs
    // it, and a token pasted into a script is exactly what this job is for.
    const exempted = all.flatMap(pathPatterns).filter((p) => p.includes('local/scripts'))
    expect(exempted).toEqual([])
  })
})
