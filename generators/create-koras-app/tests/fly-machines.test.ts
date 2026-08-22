import { describe, it, expect } from 'vitest'
import { execFileSync, spawnSync } from 'node:child_process'
import { mkdtempSync, writeFileSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

/**
 * The step that makes sure a deployed Fly machine is actually running.
 *
 * This is behavioural rather than structural on purpose. Two earlier versions
 * of the step were wrong in ways no amount of reading the file would reveal:
 * the first asked whether machines were running once and accepted the answer,
 * and the second waited for `created` to clear but did its waiting against the
 * same `machines list` endpoint whose staleness was the problem. Both looked
 * careful. Both failed real deployments of healthy services.
 *
 * So the step is extracted from the workflow and run, against a flyctl that
 * reproduces the disagreement.
 */

const WORKFLOW = join(
  __dirname, '..', '..', '..',
  'profiles', 'control-plane', 'template', '.github', 'workflows', 'deploy.yml',
)
const HARNESS = join(__dirname, 'fly', 'run-case.sh')

/** Pulls the step's shell out of the workflow without a YAML dependency. */
function extractStep(): string {
  const lines = readFileSync(WORKFLOW, 'utf8').replace(/\r/g, '').split('\n')
  const start = lines.findIndex((l) => l.includes('Make sure the machines are actually running'))
  expect(start).toBeGreaterThan(-1)

  const runAt = lines.findIndex((l, i) => i > start && l.trim() === 'run: |')
  expect(runAt).toBeGreaterThan(start)

  const body: string[] = []
  for (const line of lines.slice(runAt + 1)) {
    if (line.trim() !== '' && !line.startsWith('          ')) break
    body.push(line.slice(10))
  }
  // The app name is a GitHub expression; the harness does not run in Actions.
  return body.join('\n').replace(/app="\$\{\{.*?\}\}"/, 'app="test-scheduler-dev"')
}

function have(binary: string): boolean {
  return spawnSync(binary, ['--version'], { shell: false }).status === 0
}

// jq and bash are present on the ubuntu runners this pipeline targets, and on
// a developer machine with Git Bash. Skipping is better than a false pass.
const runnable = have('bash') && have('jq')

describe.skipIf(!runnable)('a deployed machine is left running', () => {
  const dir = mkdtempSync(join(tmpdir(), 'fly-step-'))
  const step = join(dir, 'step.sh')
  writeFileSync(step, extractStep(), 'utf8')

  const run = (initial: string, mode: 'lies' | 'honest', transition: 'yes' | 'no') =>
    execFileSync('bash', [HARNESS, step, initial, mode, transition], {
      encoding: 'utf8',
      timeout: 120_000,
    })

  it('starts a machine the list reports stale', () => {
    // Exactly the failure: the list says stopped, the machine is created, and
    // Fly refuses the start with failed_precondition. The step must treat that
    // refusal as information and look again, not as a reason to fail the job.
    const out = run('[{"id":"m1","state":"created"}]', 'lies', 'yes')
    expect(out).toContain('"state":"started"')
    expect(out).toContain('All machines running')
  })

  it('starts a stopped machine', () => {
    // The original defect: worker and scheduler have no http_service, so Fly
    // has no reason to start them and a green deploy left them stopped.
    const out = run('[{"id":"m1","state":"stopped"}]', 'honest', 'no')
    expect(out).toContain('"state":"started"')
  })

  it('leaves a running machine alone', () => {
    const out = run('[{"id":"m1","state":"started"}]', 'honest', 'no')
    expect(out).toContain('All machines running')
  })

  it('fails when a machine never starts', () => {
    // The deadline has to be able to fail, or every case above passes for the
    // wrong reason. `suspended` is never transitioned by the harness and the
    // fake refuses nothing, so the only way out is the timeout.
    const slow = join(dir, 'slow.sh')
    writeFileSync(slow, extractStep().replace('+ 300 ))', '+ 10 ))'), 'utf8')
    const result = spawnSync('bash', [HARNESS, slow, '[{"id":"m1","state":"created"}]', 'honest', 'no'], {
      encoding: 'utf8',
      timeout: 120_000,
    })
    expect(result.status).not.toBe(0)
    expect(result.stdout + result.stderr).toContain('still not running')
  })
})
