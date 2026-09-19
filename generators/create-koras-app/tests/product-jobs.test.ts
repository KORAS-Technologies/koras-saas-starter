import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import yaml from 'js-yaml'
import { templatePath } from './template-path'

/**
 * The background job contract, checked from the template text.
 *
 * PLAT-F1. Before 2026-09-19 nothing in a generated product could enqueue
 * anything: the worker ran nine cron sweeps, `koras-queue` was a one-line
 * comment, and the three request paths that kept working after the response
 * used FastAPI background tasks, which run in the API process and are lost
 * when it restarts. `enqueue_job` appeared nowhere in the repository.
 *
 * Four properties are worth a structural test, because each of them would fail
 * silently rather than loudly.
 *
 * **The extension point has both halves.** `PRODUCT_CRON_JOBS` took cron jobs
 * only, so a product needing on-demand work had to edit `worker.py` — which is
 * generated, and which the next sync reverts. A product that did so would lose
 * its own tasks on an upgrade and find out when they stopped running.
 *
 * **The package is really installed.** Its manifest declared no dependencies
 * at all while four services declared a dependency on it. A module importing
 * the queue library from a package whose manifest never asked for it works for
 * exactly as long as something else happens to bring it.
 *
 * **Jobs are foundation, not a capability.** By the rule at
 * `profiles/product/manifest.yaml`, a thing foundation code reaches may not be
 * gated. The API's lifespan builds the queue, so gating it would give a
 * product an application that fails at startup.
 *
 * **The worker actually reads the list.** `worker_functions(PRODUCT_TASKS)`
 * missing from `functions` is a product whose tasks enqueue successfully and
 * land nowhere — the queue accepts the job and no worker claims it.
 */

const PRODUCT = join(templatePath('product', 'package.json.hbs'), '..')
const PROFILE = join(PRODUCT, '..')
const SHARED = join(PROFILE, '..', '_shared', 'template')
const CONTROL_PLANE = join(PROFILE, '..', 'control-plane', 'template')

function read(root: string, ...segments: string[]): string {
  return readFileSync(join(root, ...segments), 'utf8').split(String.fromCharCode(13)).join('')
}

type Manifest = {
  template_map: { capabilities: Record<string, string | string[]> }
}

function capabilityPaths(): string[] {
  const manifest = yaml.load(
    readFileSync(join(PROFILE, 'manifest.yaml'), 'utf8'),
  ) as Manifest
  return Object.values(manifest.template_map.capabilities ?? {}).flatMap((entry) =>
    typeof entry === 'string' ? [entry] : entry,
  )
}

describe('the background job contract', () => {
  it('ships a queue package that exports a seam rather than a comment', () => {
    const index = read(SHARED, 'python-packages/koras-queue/src/koras_queue/__init__.py')

    // The three parts the ADR names. A re-export dropped here is an import
    // error in a generated project, which is loud — but it is loud at
    // deploy time rather than here.
    for (const symbol of ['queue_for', 'worker_functions', 'TaskDefinition', 'BoundTask']) {
      expect(index).toContain(symbol)
    }

    for (const module of ['tasks.py', 'queue.py', 'worker.py']) {
      expect(
        existsSync(join(SHARED, 'python-packages/koras-queue/src/koras_queue', module)),
      ).toBe(true)
    }

    // The state it was in until 2026-09-19, asserted as gone rather than
    // remembered: a package whose whole content was a note to implement it.
    expect(index.trim()).not.toBe('# koras-queue — implement as needed')
  })

  it('declares the queue library in every profile that ships the package', () => {
    // The Control Plane's manifest had no dependencies and no packages table
    // while its worker declared a dependency on the package. Both profiles are
    // asserted, because the one that was wrong is the one nobody reads.
    for (const root of [PRODUCT, CONTROL_PLANE]) {
      const manifest = read(root, 'python-packages/koras-queue/pyproject.toml')
      expect(manifest).toMatch(/dependencies\s*=\s*\[[^\]]*arq/)
      expect(manifest).toContain('packages = ["src/koras_queue"]')
    }
  })

  it('gives a product somewhere to register on-demand work', () => {
    const product = read(PRODUCT, 'services/worker/koras_worker/tasks/product.py')

    expect(product).toContain('PRODUCT_CRON_JOBS: list[CronJob] = []')
    expect(product).toContain('PRODUCT_TASKS: list[BoundTask] = []')
    expect(product).toContain('from koras_queue import BoundTask')

    // This file is a plain `.py`, not a template. A Handlebars token written
    // into its documentation would reach a generated project verbatim.
    expect(product).not.toContain('{{')
  })

  it('wires the registered tasks into what the worker runs', () => {
    const worker = read(PRODUCT, 'services/worker/koras_worker/worker.py.hbs')

    expect(worker).toContain('from koras_queue import worker_functions')
    expect(worker).toContain('PRODUCT_CRON_JOBS, PRODUCT_TASKS')
    expect(worker).toContain('worker_functions(PRODUCT_TASKS)')

    // The line this replaced. A product whose worker still had it would
    // enqueue happily and never run anything.
    expect(worker).not.toContain('functions = [example_task]\n')
  })

  it('opens one queue for the application and closes it', () => {
    const main = read(PRODUCT, 'services/api/koras_api/main.py.hbs')

    expect(main).toContain('from koras_queue import queue_for')
    expect(main).toContain('app.state.jobs = queue_for(settings.redis_url)')
    expect(main).toContain('await app.state.jobs.aclose()')

    const jobs = read(PRODUCT, 'services/api/koras_api/core/jobs.py')
    expect(jobs).toContain('JobsDep = Annotated[JobQueue, Depends(job_queue)]')
  })

  it('declares the queue package as an API dependency', () => {
    // It was declared before anything imported it. Now something does, and the
    // declaration has to survive: the generated API imports `koras_queue` in
    // its own `main.py`, so a dropped dependency is an application that does
    // not start.
    const api = read(PRODUCT, 'services/api/pyproject.toml.hbs')
    expect(api).toContain('koras-queue')
    expect(api).toMatch(/koras-queue\s*=\s*\{\s*workspace\s*=\s*true\s*\}/)
  })

  it('keeps jobs out of every capability gate', () => {
    // Foundation, by the manifest's own rule: the API lifespan builds the
    // queue, so a product generated without it would fail at startup rather
    // than lose a feature.
    const gated = capabilityPaths()
    for (const path of gated) {
      expect(path).not.toContain('koras-queue')
      expect(path).not.toContain('core/jobs.py')
      expect(path).not.toContain('tasks/product.py')
    }
  })

  it('tests the seam rather than only shipping it', () => {
    // The package has no production caller on the day it ships — its first one
    // is a notification dispatch and an import run. A seam with no caller and
    // no test is a seam nobody knows works.
    const tests = read(SHARED, 'python-packages/koras-queue/tests/test_queue.py')
    expect(tests).toContain('def test_a_job_without_a_tenant_is_refused')
    expect(tests).toContain('def test_a_payload_named_like_a_credential_is_refused')
    expect(tests).toContain('async def test_a_failing_task_asks_for_the_declared_delay')
  })
})
