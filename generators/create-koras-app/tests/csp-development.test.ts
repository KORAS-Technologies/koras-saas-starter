import { describe, it, expect, beforeAll } from 'vitest'
import { join } from 'node:path'
import { loadProfile } from '../src/profiles/index.js'
import { resolveSelections } from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'

/**
 * The development policy may grant `'unsafe-eval'`. The production one may not.
 *
 * GR-248. Next's development runtime compiles modules with `eval`, so a policy
 * with a nonce and `'strict-dynamic'` and no `'unsafe-eval'` is one React
 * cannot hydrate under: the page arrives, the runtime is refused, and nothing
 * becomes interactive. The fix grants the keyword to `next dev` alone.
 *
 * "Alone" is the whole risk, and it rests on one equality. `next build` inlines
 * `process.env.NODE_ENV`, so in a production build the predicate is
 * `'production' === 'development'` and the branch is compiled out -- but only
 * because the comparison is an equality against the one mode that needs it. The
 * tempting `!== 'production'` would admit `test`, `undefined` and anything else
 * somebody ever puts there, and every Koras environment -- dev, test, stg and
 * prod alike -- is a production Next build, so that predicate would have
 * shipped `'unsafe-eval'` to customers on four environments out of four.
 *
 * These are structural assertions over the rendered templates. What the built
 * artefact actually serves is R1's job (`profiles/_shared/template/e2e/`), and
 * neither substitutes for the other: this cannot see a build, and R1 cannot see
 * a predicate.
 */

function render(
  profile: 'product' | 'control-plane',
  applications: Record<string, boolean> = {},
): Map<string, string> {
  const { manifest, defaults } = loadProfile(profile)
  const selections = resolveSelections(manifest, defaults)
  // Marketing is optional and off by default, so the only way to assert
  // anything about it is to select it the way `--with marketing` would.
  Object.assign(selections.applications, applications)
  const ctx = buildContext({
    projectName: `a-${profile}`,
    projectSlug: `a-${profile}`,
    profile,
    manifest,
    defaults,
    selections,
    outputDir: join(__dirname, 'unused'),
    dryRun: true,
    provision: false,
  })
  return new Map(renderTemplate(ctx).map((f) => [f.outputPath, f.content.toString()]))
}

/** The applications that emit a policy. Marketing is not one, and is checked separately. */
const CSP_APPS: Record<'product' | 'control-plane', string[]> = {
  product: ['apps/web/src/middleware.ts', 'apps/admin/src/middleware.ts'],
  'control-plane': ['apps/admin/src/middleware.ts', 'apps/portal/src/middleware.ts'],
}

/** The exact predicate. An equality, against the one Next execution mode that needs the keyword. */
const PREDICATE = "process.env.NODE_ENV === 'development'"

const MARKETING = 'apps/marketing/src/middleware.ts'

function scriptSrcLine(source: string): string {
  // Every assertion about the directive reads this one line, so taking the
  // *first* match would mean a second `script-src` -- a report-only variant, a
  // gated alternative, a second policy builder -- left all of them reading a
  // line that is no longer the whole story. Requiring exactly one is what
  // makes the rest of this file say something about the policy rather than
  // about whichever line happened to come first.
  const found = source.split('\n').filter((l) => l.includes("script-src 'self'"))
  expect(found, 'expected exactly one script-src line in this middleware').toHaveLength(1)
  return found[0] as string
}

function occurrences(source: string, needle: string): number {
  return source.split(needle).length - 1
}

describe.each(['product', 'control-plane'] as const)('%s: development-only unsafe-eval', (profile) => {
  let files: Map<string, string>
  beforeAll(() => {
    files = render(profile)
  })

  it('renders every CSP-bearing application', () => {
    // Anti-vacuity. Every assertion below loops over this list, and a list that
    // silently stopped matching the templates would make all of them pass by
    // checking nothing.
    expect(CSP_APPS[profile].length).toBeGreaterThan(0)
    for (const path of CSP_APPS[profile]) {
      expect(files.has(path), `${path} was not rendered`).toBe(true)
    }
  })

  it.each(CSP_APPS[profile])('%s carries the exact development predicate', (path) => {
    expect(files.get(path) as string).toContain(PREDICATE)
  })

  it.each(CSP_APPS[profile])('%s grants unsafe-eval only under that predicate', (path) => {
    const source = files.get(path) as string

    // Every mention of the keyword in the file is on the one line that also
    // carries the predicate. If a second appeared anywhere -- another
    // directive, a second branch, a comment that became code -- this fails.
    const evalLines = source.split('\n').filter((l) => l.includes('unsafe-eval'))
    expect(evalLines, `${path}: expected exactly one line mentioning unsafe-eval`).toHaveLength(1)
    expect(evalLines[0] as string).toContain(PREDICATE)

    // And the production side of that conditional grants nothing. Asserted on
    // the text of the alternative rather than inferred from the predicate.
    expect(evalLines[0] as string).toMatch(/:\s*''/)
  })

  it.each(CSP_APPS[profile])('%s keeps the production script-src intact', (path) => {
    const line = scriptSrcLine(files.get(path) as string)
    expect(line, `${path}: script-src lost its nonce`).toContain("'nonce-${nonce}'")
    expect(line, `${path}: script-src lost strict-dynamic`).toContain("'strict-dynamic'")
    expect(line, `${path}: script-src must not grant unsafe-inline`).not.toContain("'unsafe-inline'")
  })

  it.each(CSP_APPS[profile])('%s actually interpolates the constant into script-src', (path) => {
    // The assertion this file most needed and did not have. Everything else
    // reads either the declaration or the directive; nothing joined them, so
    // deleting the single token `${DEVELOPMENT_EVAL}` from the directive left a
    // dead constant, every other assertion satisfied, and GR-248 back in full.
    // Found by the independent review, reproduced, and it is the PLAT-DEF-010
    // class arriving in the file whose own header sets out to refuse it.
    const source = files.get(path) as string
    const line = scriptSrcLine(source)
    expect(line, `${path}: script-src no longer interpolates DEVELOPMENT_EVAL`).toContain(
      "'strict-dynamic'${DEVELOPMENT_EVAL}",
    )
    // Exactly once, and in that directive: a second interpolation would put the
    // keyword in some other directive, which the line assertion above cannot see.
    expect(
      occurrences(source, '${DEVELOPMENT_EVAL}'),
      `${path}: DEVELOPMENT_EVAL must be interpolated exactly once`,
    ).toBe(1)
  })

  it.each(CSP_APPS[profile])('%s declares no narrower script directive', (path) => {
    // `script-src-elem` and `script-src-attr` override `script-src` for what
    // they cover, so a keyword in either is fully effective and invisible to
    // every assertion above.
    const source = files.get(path) as string
    expect(occurrences(source, 'script-src-elem'), `${path}: unexpected script-src-elem`).toBe(0)
    expect(occurrences(source, 'script-src-attr'), `${path}: unexpected script-src-attr`).toBe(0)
  })

  it.each(CSP_APPS[profile])('%s uses no looser or deployment-stage predicate', (path) => {
    const source = files.get(path) as string
    // Each of these would widen the grant beyond `next dev`. VERCEL_ENV and the
    // Koras stage names are wrong for a different reason: dev, test, stg and
    // prod are all production Next builds, so a stage cannot distinguish the
    // one execution mode that needs eval.
    expect(source).not.toContain("NODE_ENV !== 'production'")
    expect(source).not.toContain("NODE_ENV != 'production'")
    expect(source).not.toContain('NODE_ENV !==')
    expect(source).not.toContain('NODE_ENV !=')
    expect(source).not.toContain('VERCEL_ENV')
  })
})

describe('product: marketing is excluded', () => {
  let files: Map<string, string>
  beforeAll(() => {
    files = render('product', { marketing: true })
  })

  it('has a middleware but emits no policy', () => {
    // Stated rather than assumed: the exclusion is only correct while marketing
    // sets no CSP of its own. The day it sets one, this fails and the decision
    // gets made again instead of being inherited.
    expect(files.has(MARKETING), 'marketing middleware was not rendered').toBe(true)
    const source = files.get(MARKETING) as string
    expect(source).not.toContain('script-src')
    expect(source).not.toContain('Content-Security-Policy')
  })

  it('carries no GR-248 conditional', () => {
    const source = files.get(MARKETING) as string
    expect(source).not.toContain('unsafe-eval')
    expect(source).not.toContain(PREDICATE)
  })
})

/**
 * The predicate's semantics, evaluated rather than described.
 *
 * Everything above asserts the *text* of the conditional. That catches an edit
 * to it, and would say nothing at all if the equality itself were wrong. So
 * this lifts the expression out of the rendered middleware and runs it under
 * each value `NODE_ENV` can hold, which is the only way to show that `test` and
 * `undefined` are refused rather than merely believed to be.
 */
describe.each(['product', 'control-plane'] as const)('%s: equality semantics', (profile) => {
  let files: Map<string, string>
  beforeAll(() => {
    files = render(profile)
  })

  /** The right-hand side of `const DEVELOPMENT_EVAL = ...`, taken from the rendered file. */
  function expression(path: string): string {
    const line = (files.get(path) as string)
      .split('\n')
      .find((l) => l.includes('const DEVELOPMENT_EVAL'))
    expect(line, `${path}: no DEVELOPMENT_EVAL declaration`).toBeDefined()
    const rhs = (line as string).split('=').slice(1).join('=').trim()
    // Shape-checked before it is evaluated, so this never runs arbitrary text --
    // but deliberately loose about *which* comparison and *which* value, so that
    // the semantics below are decided by running the expression rather than by
    // this pattern having already pinned the answer.
    expect(rhs, `${path}: unexpected declaration shape`).toMatch(
      /^process\.env\.NODE_ENV [!=]==? '[A-Za-z]+' \? " '[a-z-]+'" : ''$/,
    )
    return rhs
  }

  it.each(CSP_APPS[profile])('%s grants the keyword to development alone', (path) => {
    const rhs = expression(path)
    // The real expression, not a re-typed copy of it: a divergence between what
    // ships and what is measured is exactly what this is here to prevent.
    const evaluate = (nodeEnv: string | undefined): string =>
      new Function('process', `return (${rhs})`)({ env: { NODE_ENV: nodeEnv } }) as string

    expect(evaluate('development'), 'development must grant it').toBe(" 'unsafe-eval'")
    expect(evaluate('production'), 'production must not').toBe('')
    expect(evaluate('test'), 'test must not').toBe('')
    expect(evaluate(undefined), 'an unset NODE_ENV must not').toBe('')
    expect(evaluate('staging'), 'an unexpected value must not').toBe('')
    expect(evaluate('Development'), 'the comparison is case-sensitive').toBe('')
  })
})
