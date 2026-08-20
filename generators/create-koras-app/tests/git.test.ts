import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { mkdirSync, rmSync, existsSync, writeFileSync } from 'node:fs'
import {
  findForbiddenArtifacts,
  initAndPushToDevelop,
  needsWindowsShell,
  type CommandExecutor,
} from '../src/git.js'

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

describe('needsWindowsShell', () => {
  it('shells out to npm-family commands on Windows', () => {
    // `pnpm` is a .cmd shim there: spawning it without a shell fails ENOENT.
    expect(needsWindowsShell('pnpm', 'win32')).toBe(true)
    expect(needsWindowsShell('npm', 'win32')).toBe(true)
    expect(needsWindowsShell('npx', 'win32')).toBe(true)
    expect(needsWindowsShell('corepack', 'win32')).toBe(true)
  })

  it('never shells out for git, on any platform', () => {
    // git args carry a Terraform-supplied URL and a commit message.
    expect(needsWindowsShell('git', 'win32')).toBe(false)
    expect(needsWindowsShell('git', 'linux')).toBe(false)
    expect(needsWindowsShell('git', 'darwin')).toBe(false)
  })

  it('never shells out on POSIX platforms', () => {
    expect(needsWindowsShell('pnpm', 'linux')).toBe(false)
    expect(needsWindowsShell('pnpm', 'darwin')).toBe(false)
  })
})

describe('confirmation before committing', () => {
  it('does nothing at all when the operator declines', async () => {
    const projectRoot = makeProjectDir('declined')
    const { calls, exec } = captureExec()

    await initAndPushToDevelop({
      projectRoot,
      repositoryFullName: 'org/declined',
      exec,
      confirm: () => Promise.resolve(false),
    })

    // Not even pnpm install: declining must leave the tree exactly as it is.
    expect(calls).toHaveLength(0)
    expect(existsSync(join(projectRoot, '.git'))).toBe(false)
  })

  it('proceeds when the operator accepts', async () => {
    const projectRoot = makeProjectDir('accepted')
    const { calls, exec } = captureExec()

    await initAndPushToDevelop({
      projectRoot,
      repositoryFullName: 'org/accepted',
      exec,
      confirm: () => Promise.resolve(true),
    })

    expect(calls.map((c) => `${c.cmd} ${c.args.join(' ')}`)).toContain('git push origin develop')
  })

  it('never asks when the project is already a repository', async () => {
    const projectRoot = makeProjectDir('already')
    mkdirSync(join(projectRoot, '.git'))
    let asked = false
    const { calls, exec } = captureExec()

    await initAndPushToDevelop({
      projectRoot,
      repositoryFullName: 'org/already',
      exec,
      confirm: () => {
        asked = true
        return Promise.resolve(true)
      },
    })

    // An existing repository has its own history and remote; re-initialising
    // over it is not a question worth asking.
    expect(asked).toBe(false)
    expect(calls).toHaveLength(0)
  })
})

describe('the forbidden-artifact guard', () => {
  it('still finds state files on disk', () => {
    const projectRoot = makeProjectDir('artifacts')
    mkdirSync(join(projectRoot, 'infrastructure'), { recursive: true })
    writeFileSync(join(projectRoot, 'infrastructure', 'terraform.tfstate'), '{}')

    expect(findForbiddenArtifacts(projectRoot)).toEqual(['infrastructure/terraform.tfstate'])
  })

  it('does not walk into .terraform at all', () => {
    // Terraform's own cache. Its terraform.tfstate records the backend, not
    // resource state, and the directory is gitignored in every project.
    const projectRoot = makeProjectDir('cache')
    mkdirSync(join(projectRoot, '.terraform'), { recursive: true })
    writeFileSync(join(projectRoot, '.terraform', 'terraform.tfstate'), '{}')

    expect(findForbiddenArtifacts(projectRoot)).toEqual([])
  })

  it('asks git whether each candidate would actually be committed', async () => {
    // A plan file the generated .gitignore already covers cannot reach a
    // commit, so refusing the push over it blocks work for no gain.
    const projectRoot = makeProjectDir('ignored')
    mkdirSync(join(projectRoot, 'infrastructure', 'terraform'), { recursive: true })
    writeFileSync(join(projectRoot, 'infrastructure', 'terraform', 'tfplan'), 'PK')

    const calls: Array<{ cmd: string; args: string[] }> = []
    const exec: CommandExecutor = (cmd, args) => {
      calls.push({ cmd, args })
      // exit 0 from check-ignore: the path IS ignored.
      return Promise.resolve(0)
    }

    await initAndPushToDevelop({
      projectRoot,
      repositoryFullName: 'org/ignored',
      exec,
      confirm: () => Promise.resolve(true),
    })

    expect(calls.some((c) => c.args[0] === 'check-ignore')).toBe(true)
    expect(calls.map((c) => `${c.cmd} ${c.args.join(' ')}`)).toContain('git push origin develop')
  })

  it('still refuses when git would commit the state file', async () => {
    const projectRoot = makeProjectDir('unignored')
    writeFileSync(join(projectRoot, 'terraform.tfstate'), '{}')

    const exec: CommandExecutor = (_cmd, args) =>
      // exit 1 from check-ignore: the path is NOT ignored, so it would be added.
      Promise.resolve(args[0] === 'check-ignore' ? 1 : 0)

    await expect(
      initAndPushToDevelop({
        projectRoot,
        repositoryFullName: 'org/unignored',
        exec,
        confirm: () => Promise.resolve(true),
      }),
    ).rejects.toThrow('Refusing to commit')
  })
})
