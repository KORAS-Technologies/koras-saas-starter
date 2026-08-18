import { spawn } from 'node:child_process'
import { existsSync, rmSync } from 'node:fs'
import { join } from 'node:path'

/** Injectable executor — accepts any command so tests can stub both git and pnpm. */
export type CommandExecutor = (cmd: string, args: string[], cwd: string) => Promise<number>

/** @deprecated Use CommandExecutor */
export type GitExecutor = CommandExecutor

export interface GitInitOptions {
  projectRoot: string
  /** org/repo full name, e.g. "KORAS-Technologies/sample-product" */
  repositoryFullName: string
  exec?: CommandExecutor
}

function spawnCmd(cmd: string, args: string[], cwd: string): Promise<number> {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { cwd, stdio: 'inherit', shell: false })
    child.on('error', reject)
    child.on('close', (code) => resolve(code ?? 1))
  })
}

async function run(
  cmd: string,
  args: string[],
  cwd: string,
  exec?: CommandExecutor,
): Promise<number> {
  return exec ? exec(cmd, args, cwd) : spawnCmd(cmd, args, cwd)
}

/**
 * Initialises a git repository in the generated project directory, makes an
 * initial commit on top of GitHub's auto-init commit, and does a regular
 * fast-forward push to `develop`.
 *
 * Strategy: after fetching, `git update-ref` points local `develop` at the
 * remote auto-init commit before committing. Our generated commit is then a
 * direct descendant, so the push is a plain fast-forward — no force push
 * required and therefore compatible with branch protection rules.
 *
 * On any failure the `.git` directory is removed so a --provision-only retry
 * starts clean rather than silently skipping a broken partial state.
 *
 * `main`, `test`, and `staging` require PRs to receive code; they are
 * populated through the normal PR workflow from `develop`.
 */
export async function initAndPushToDevelop(options: GitInitOptions): Promise<void> {
  const { projectRoot, repositoryFullName } = options
  const exec = options.exec
  const cloneUrl = `https://github.com/${repositoryFullName}.git`
  const gitDir = join(projectRoot, '.git')
  const g = (args: string[]) => run('git', args, projectRoot, exec)

  if (existsSync(gitDir)) {
    console.log('\n  Git repository already initialised — skipping.')
    return
  }

  try {
    // Generate pnpm-lock.yaml before committing — CI needs the lock file.
    console.log('\n==> pnpm install')
    let code = await run('pnpm', ['install'], projectRoot, exec)
    if (code !== 0) throw new Error('pnpm install failed')

    console.log('\n==> git init')
    code = await g(['init', '-b', 'develop'])
    if (code !== 0) throw new Error('git init failed')

    code = await g(['remote', 'add', 'origin', cloneUrl])
    if (code !== 0) throw new Error('git remote add failed')

    code = await g(['fetch', 'origin'])
    if (code !== 0) throw new Error('git fetch failed')

    // Graft local develop onto the remote auto-init commit so the push is a
    // plain fast-forward and branch protection allows it without force.
    code = await g(['update-ref', 'refs/heads/develop', 'refs/remotes/origin/develop'])
    if (code !== 0) throw new Error('git update-ref failed')

    console.log('\n==> git commit')
    code = await g(['add', '.'])
    if (code !== 0) throw new Error('git add failed')

    code = await g([
      '-c', 'user.email=generator@koras.dev',
      '-c', 'user.name=KORAS Generator',
      'commit', '-m', 'chore: initial project generation',
    ])
    if (code !== 0) throw new Error('git commit failed')

    console.log('\n==> git push origin develop')
    code = await g(['push', 'origin', 'develop'])
    if (code !== 0) throw new Error('git push to develop failed')

    await g(['branch', '--set-upstream-to=origin/develop', 'develop'])
  } catch (err) {
    // Remove the partial repo so the next --provision-only retry starts clean.
    if (!exec && existsSync(gitDir)) rmSync(gitDir, { recursive: true, force: true })
    throw err
  }
}



