import { describe, it, expect } from 'vitest'
import { doctor } from '../src/doctor/run.js'
import { REPO_ROOT, healthyEnv, healthyExec, healthyRoutes, response, stubFetch } from './helpers.js'

async function run(namespaces: unknown, status = 200) {
  return doctor({
    env: healthyEnv(),
    fetchImpl: stubFetch({
      ...healthyRoutes(),
      'integrations/git-namespaces': response(status, namespaces),
    }),
    exec: healthyExec(),
    repoRoot: REPO_ROOT,
  })
}

function failedRows(output: string): string[] {
  return output
    .split('\n')
    .filter((l) => l.endsWith('✗'))
    .map((l) => l.replace('✗', '').trimEnd())
}

describe("Vercel's GitHub connection", () => {
  it('passes when the App is installed on the configured org', async () => {
    const { output } = await run([{ provider: 'github', slug: 'koras-org' }])
    expect(failedRows(output)).toEqual([])
  })

  it('matches the org case-insensitively', async () => {
    // GitHub preserves an org's canonical casing; the env var may not.
    const { output } = await run([{ provider: 'github', slug: 'KORAS-ORG' }])
    expect(failedRows(output)).toEqual([])
  })

  // The regression: a valid token and a valid team still produce
  // `repo_not_found` at apply time when the App is installed only on the
  // personal account of whoever connected it — which is the default.
  it('fails when only a personal account is connected', async () => {
    const { output, code } = await run([
      { provider: 'github', slug: 'kkora', ownerType: 'user' },
    ])
    expect(failedRows(output)).toEqual(['Vercel'])
    expect(output).toContain('not installed on "koras-org"')
    expect(output).toContain('Connected: kkora')
    expect(code).toBe(1)
  })

  it('reports when nothing at all is connected', async () => {
    const { output } = await run([])
    expect(failedRows(output)).toEqual(['Vercel'])
    expect(output).toContain('Connected: none')
  })
})
