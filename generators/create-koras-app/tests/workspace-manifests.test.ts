import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { templatePath } from './template-path.js'

/**
 * A service image must contain every workspace member the root manifest names.
 *
 * `uv sync --no-dev` does not skip *reading* the dev group. It parses the whole
 * root manifest first, and every `{ workspace = true }` entry in
 * `[tool.uv.sources]` has to resolve to a member it can find on disk, installed
 * or not. A Dockerfile that copies only its own service's `pyproject.toml`
 * therefore fails on the root project itself:
 *
 *     x Failed to build `koras-e2e-shop @ file:///app`
 *     |-> Failed to parse entry in group `dev`: `koras-e2e-shop-api`
 *     `-> `koras-e2e-shop-api` references a workspace in `tool.uv.sources`,
 *         but is not a workspace member
 *
 * which is what the first deployment of a generated product's worker did on
 * 2026-08-30. The API image was unaffected -- it copies `services/api` by
 * definition -- so the fault was invisible to the one service anybody had built
 * by hand, and appeared only on the three that are not the API.
 *
 * Asserted from the manifest rather than against a list of paths, so adding a
 * workspace source to the root pyproject fails here until the images that need
 * it copy it.
 */

const PROFILES = ['product', 'control-plane'] as const

/** Member directories a profile could render, from both template layers. */
function memberDirs(profile: string, parent: string): string[] {
  const seen = new Set<string>()
  for (const layer of [profile, '_shared']) {
    const dir = join(__dirname, '..', '..', '..', 'profiles', layer, 'template', parent)
    if (!existsSync(dir)) continue
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) seen.add(entry.name)
    }
  }
  return [...seen].sort()
}

/** The `[project] name` a member declares, template placeholders intact. */
function declaredName(profile: string, parent: string, dir: string): string | undefined {
  for (const file of ['pyproject.toml', 'pyproject.toml.hbs']) {
    let path: string
    try {
      path = templatePath(profile, parent, dir, file)
    } catch {
      continue
    }
    const match = /^name = "(.+)"$/m.exec(readFileSync(path, 'utf8'))
    if (match) return match[1]
  }
  return undefined
}

/** Package names the root manifest points at the workspace. */
function workspaceSources(profile: string): string[] {
  const root = readFileSync(templatePath(profile, 'pyproject.toml.hbs'), 'utf8')
  const after = root.split(/^\[tool\.uv\.sources\]$/m)[1]
  expect(after, `${profile}: no [tool.uv.sources] in the root pyproject`).toBeTruthy()
  const block = after.split(/^\[/m)[0]
  return [...block.matchAll(/^"?([^"\s=]+)"?\s*=\s*\{[^}]*workspace\s*=\s*true/gm)].map((m) => m[1])
}

describe.each(PROFILES)('%s: service images carry the workspace members', (profile) => {
  // A service with no pyproject is not a uv workspace member, and its image is
  // not built with uv -- `services/clamd` is a container around somebody else's
  // daemon, and the root manifest EXCLUDES it from the workspace by name (see
  // `tests/product-clamd.test.ts`). The rule below exists because uv reads every
  // `workspace = true` entry when it builds a member; an image that does not run
  // uv has nothing to satisfy. This used to be every directory with a Dockerfile,
  // which was the same set only while every service was Python.
  const isMember = (s: string): boolean => declaredName(profile, 'services', s) !== undefined

  const services = memberDirs(profile, 'services').filter((s) => {
    if (!isMember(s)) return false
    try {
      templatePath(profile, 'services', s, 'Dockerfile')
      return true
    } catch {
      return false
    }
  })

  it('has service images to check', () => {
    expect(services.length).toBeGreaterThan(0)
  })

  it.each(services)('services/%s', (service) => {
    const dockerfile = readFileSync(
      templatePath(profile, 'services', service, 'Dockerfile'),
      'utf8',
    )

    for (const source of workspaceSources(profile)) {
      // python-packages/ is copied as a tree, so every member under it is
      // present the moment that one line is there. services/ is not: each
      // manifest is copied by name, to keep the dependency layer cacheable.
      const inPackages = memberDirs(profile, 'python-packages').some(
        (dir) => declaredName(profile, 'python-packages', dir) === source,
      )
      if (inPackages) {
        expect(dockerfile, `${service}: ${source} lives in python-packages/`).toContain(
          'COPY python-packages/ ./python-packages/',
        )
        continue
      }

      const dir = memberDirs(profile, 'services').find(
        (d) => declaredName(profile, 'services', d) === source,
      )
      expect(dir, `${profile}: no workspace member declares name "${source}"`).toBeTruthy()
      expect(
        dockerfile,
        `services/${service}/Dockerfile must copy services/${dir}/pyproject.toml -- ` +
          `the root manifest points "${source}" at the workspace, and uv reads that ` +
          `entry even under --no-dev`,
      ).toContain(`COPY services/${dir}/pyproject.toml ./services/${dir}/`)
    }
  })
})
