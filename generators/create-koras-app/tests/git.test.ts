import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { mkdirSync, rmSync, existsSync, writeFileSync } from 'node:fs'
import { initAndPushToDevelop, type CommandExecutor } from '../src/git.js'

const ROOT = join(tmpdir(), `koras-git-${process.pid}-${Date.now()}`)

beforeEach(() => mkdirSync(ROOT, { recursive: true }))
afterEach(() => { if (existsSync(ROOT)) rmSync(ROOT, { recursive: true, force: true }) })

function makeProjectDir(name: string): string {
  const dir = join(ROOT, name)
  mkdirSync(dir, { recursive: true })
  writeFileSync(join(dir, 'README.md'), `# ${name}\n`)
  return dir
}

function captureExec(): { calls: Array<{ cmd: string; args: string[] }>; exec: CommandExecutor } {
  const calls: Array<{ cmd: string; args: string[] }> = []
  const exec: CommandExecutor = (cmd, args) => {
    calls.push({ cmd, args })
    return Promise.resolve(0)
  }
  return { calls, exec }
}

describe('initAndPushToDevelop', () => {
  it('runs the expected command sequence', async () => {
    const projectRoot = makeProjectDir('myapp')
    const { calls, exec } = captureExec()

    await initAndPushToDevelop({
      projectRoot,
      repositoryFullName: 'KORAS-Technologies/myapp',
      exec,
    })

    const steps = calls.map((c) => `${c.cmd} ${c.args.join(' ')}`)
    // pnpm install must come first so lock file exists before git add
    expect(steps[0]).toBe('pnpm install')
    expect(steps.some((s) => s.startsWith('git init'))).toBe(true)
    expect(steps).toContain('git remote add origin https://github.com/KORAS-Technologies/myapp.git')
    expect(steps).toContain('git fetch origin')
    expect(steps).toContain('git update-ref refs/heads/develop refs/remotes/origin/develop')
    expect(steps.some((s) => s.includes('commit'))).toBe(true)
    expect(steps).toContain('git push origin develop')
    expect(steps).toContain('git branch --set-upstream-to=origin/develop develop')
    expect(steps.some((s) => s.includes('--force'))).toBe(false)
  })

  it('pnpm install comes before git add', async () => {
    const projectRoot = makeProjectDir('order')
    const { calls, exec } = captureExec()

    await initAndPushToDevelop({ projectRoot, repositoryFullName: 'org/order', exec })

    const steps = calls.map((c) => `${c.cmd} ${c.args.join(' ')}`)
    const pnpmIdx = steps.findIndex((s) => s === 'pnpm install')
    const addIdx = steps.findIndex((s) => s === 'git add .')
    expect(pnpmIdx).toBeLessThan(addIdx)
  })

  it('fetch comes before update-ref and commit', async () => {
    const projectRoot = makeProjectDir('order2')
    const { calls, exec } = captureExec()

    await initAndPushToDevelop({ projectRoot, repositoryFullName: 'org/order2', exec })

    const steps = calls.map((c) => `${c.cmd} ${c.args.join(' ')}`)
    const fetchIdx = steps.indexOf('git fetch origin')
    const updateIdx = steps.indexOf('git update-ref refs/heads/develop refs/remotes/origin/develop')
    const pushIdx = steps.indexOf('git push origin develop')
    expect(fetchIdx).toBeLessThan(updateIdx)
    expect(updateIdx).toBeLessThan(pushIdx)
  })

  it('skips initialisation when .git already exists', async () => {
    const projectRoot = makeProjectDir('existing')
    mkdirSync(join(projectRoot, '.git'))
    const { calls, exec } = captureExec()

    await initAndPushToDevelop({
      projectRoot,
      repositoryFullName: 'KORAS-Technologies/existing',
      exec,
    })

    expect(calls).toHaveLength(0)
  })

  it('throws when a command fails', async () => {
    const projectRoot = makeProjectDir('failing')
    let callCount = 0
    const exec: CommandExecutor = () => {
      callCount++
      return Promise.resolve(callCount === 1 ? 1 : 0) // pnpm install fails
    }

    await expect(
      initAndPushToDevelop({ projectRoot, repositoryFullName: 'org/repo', exec }),
    ).rejects.toThrow('pnpm install failed')
  })
})
