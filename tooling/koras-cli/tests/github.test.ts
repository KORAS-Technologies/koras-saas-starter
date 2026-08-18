import { describe, it, expect } from 'vitest'
import { doctor } from '../src/doctor/run.js'
import { REPO_ROOT, healthyEnv, healthyExec, healthyRoutes, response, stubFetch } from './helpers.js'

async function run(orgBody: unknown, status = 200) {
  return doctor({
    env: healthyEnv(),
    fetchImpl: stubFetch({
      ...healthyRoutes(),
      'api.github.com/orgs': response(status, orgBody),
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

describe('GitHub organization access', () => {
  it('passes when the token has real organization access', async () => {
    const { output } = await run({ login: 'koras-org', members_can_create_repositories: true })
    expect(failedRows(output)).toEqual([])
  })

  // The regression this check exists for: /orgs/{org} is a public endpoint, so
  // a token with no organization access still gets a 200. That token cannot
  // create a repository, and the failure used to surface only during
  // `terraform apply` — after other providers had already created resources.
  it('fails a token that can only read the public organization profile', async () => {
    const { output, code } = await run({ login: 'koras-org' })
    expect(failedRows(output)).toEqual(['GitHub'])
    expect(output).toContain('no access')
    expect(output).toContain('cannot create repositories')
    expect(code).toBe(1)
  })

  it('fails when the organization forbids member repository creation', async () => {
    const { output } = await run({ login: 'koras-org', members_can_create_repositories: false })
    expect(failedRows(output)).toEqual(['GitHub'])
    expect(output).toContain('does not allow members to create repositories')
  })

  it('still reports a rejected token distinctly', async () => {
    const { output } = await run({}, 401)
    expect(failedRows(output)).toEqual(['GitHub'])
    expect(output).toContain('was rejected')
  })
})
