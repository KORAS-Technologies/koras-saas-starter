import { describe, it, expect } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'

import { loadProfile } from '../src/profiles/index.js'
import { resolveSelections } from '../src/profiles/validator.js'
import { applyRecordedComponents } from '../src/cli/index.js'
import { PROJECT_MANIFEST_PATH } from '../src/generation/project-manifest.js'

/**
 * A read-only command acts on the project that exists, not the defaults of the
 * day it is run.
 *
 * `--check-drift` re-derived its component selections from the profile, so a
 * project generated with `--with scheduler` was told its scheduler was drift --
 * by the command whose whole job is to say what has drifted. Anyone who used an
 * optional component got a report they had to know to disbelieve.
 *
 * `.koras/project.yaml` records what the project was generated with, which is
 * exactly so this is knowable without the operator remembering flags they
 * passed a year ago.
 */

function listing(name: string, values: string[]): string[] {
  return values.length === 0
    ? [`  ${name}: []`]
    : [`  ${name}:`, ...values.map((v) => `    - ${v}`)]
}

function projectWith(components: {
  applications: string[]
  services: string[]
  capabilities: string[]
}): string {
  const root = join(tmpdir(), `koras-rc-${process.pid}-${Math.floor(performance.now() * 1000)}`)
  mkdirSync(join(root, '.koras'), { recursive: true })
  writeFileSync(
    join(root, PROJECT_MANIFEST_PATH),
    [
      'schema_version: 1',
      'project:',
      '  name: recorded',
      '  slug: recorded',
      '  profile: product',
      'generator:',
      '  name: create-koras-app',
      '  starter_version: 0.1.0',
      '  profile_version: 1.0.0',
      'components:',
      // An empty list is written inline. `capabilities:` with nothing under it
      // is YAML null, not an empty array, and the schema rightly refuses it --
      // which the first draft of this helper discovered by silently producing
      // a manifest that would not parse.
      ...listing('applications', components.applications),
      ...listing('services', components.services),
      ...listing('capabilities', components.capabilities),
      '',
    ].join('\n'),
    'utf8',
  )
  return root
}

function defaultSelections() {
  const { manifest, defaults } = loadProfile('product')
  return resolveSelections(manifest, defaults)
}

describe('a project’s recorded components win over today’s defaults', () => {
  it('enables a component the defaults leave off', () => {
    const selections = defaultSelections()
    expect(selections.services.scheduler, 'scheduler is off by default').toBe(false)

    const root = projectWith({
      applications: ['web'],
      services: ['api', 'scheduler'],
      capabilities: [],
    })
    try {
      applyRecordedComponents(selections, root, { overridden: [] })
      expect(selections.services.scheduler).toBe(true)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('disables a component the defaults leave on', () => {
    const selections = defaultSelections()
    expect(selections.services.worker, 'worker is on by default').toBe(true)

    const root = projectWith({ applications: ['web'], services: ['api'], capabilities: [] })
    try {
      applyRecordedComponents(selections, root, { overridden: [] })
      expect(selections.services.worker).toBe(false)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('leaves a component named on the command line alone', () => {
    // `--check-drift --with worker` on a project generated without one is a
    // question about what it would look like with the worker. Answering from
    // the recorded set would ignore the question.
    const selections = defaultSelections()
    selections.services.worker = true

    const root = projectWith({ applications: ['web'], services: ['api'], capabilities: [] })
    try {
      applyRecordedComponents(selections, root, { overridden: ['worker'] })
      expect(selections.services.worker, 'an explicit flag was overwritten').toBe(true)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('changes nothing when the project records no components', () => {
    // A manifest written before the field existed. The old behaviour was
    // correct for those projects and must survive.
    const selections = defaultSelections()
    const before = JSON.stringify(selections)

    const root = join(tmpdir(), `koras-rc-none-${process.pid}`)
    mkdirSync(join(root, '.koras'), { recursive: true })
    writeFileSync(
      join(root, PROJECT_MANIFEST_PATH),
      [
        'schema_version: 1',
        'project:',
        '  name: old',
        '  slug: old',
        '  profile: product',
        'generator:',
        '  name: create-koras-app',
        '  starter_version: 0.1.0',
        '  profile_version: 1.0.0',
        '',
      ].join('\n'),
      'utf8',
    )
    try {
      applyRecordedComponents(selections, root, { overridden: [] })
      expect(JSON.stringify(selections)).toBe(before)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('changes nothing when there is no project at all', () => {
    const selections = defaultSelections()
    const before = JSON.stringify(selections)
    applyRecordedComponents(selections, join(tmpdir(), 'koras-rc-absent'), { overridden: [] })
    expect(JSON.stringify(selections)).toBe(before)
  })

  it('changes nothing when the manifest cannot be parsed', () => {
    // Malformed is the drift report's business, and it says so more usefully.
    const selections = defaultSelections()
    const before = JSON.stringify(selections)

    const root = join(tmpdir(), `koras-rc-bad-${process.pid}`)
    mkdirSync(join(root, '.koras'), { recursive: true })
    writeFileSync(join(root, PROJECT_MANIFEST_PATH), 'this: is: not: valid: yaml:\n', 'utf8')
    try {
      applyRecordedComponents(selections, root, { overridden: [] })
      expect(JSON.stringify(selections)).toBe(before)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })
})
