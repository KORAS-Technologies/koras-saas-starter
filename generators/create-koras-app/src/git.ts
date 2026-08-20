import { spawn } from 'node:child_process'
import { existsSync, readdirSync, rmSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'

/**
 * Artifacts that must never be committed, matched by name rather than content.
 *
 * A Terraform plan or state file embeds every credential Terraform touched --
 * database passwords, generated OIDC client secrets, provider tokens. Content
 * scanners cannot see them: a plan is a zip, gitleaks decides what is an
 * archive from the file extension, and Terraform names plan files without one.
 * Measured on a real plan: `tfplan` scans as zero bytes and reports nothing,
 * while the byte-identical file named `tfplan.zip` yields 28 findings.
 *
 * So this is a path rule. It cannot be defeated by an entropy threshold, and
 * these files have no legitimate reason to be in a repository: a plan is a
 * disposable intermediate and state belongs in the remote backend.
 *
 * The plan is now written to a temporary directory (see terraform/runner.ts),
 * so nothing should ever match. That is exactly why the check is worth having:
 * it catches the artifact nobody has thought of yet, and it costs a directory
 * walk.
 */
const FORBIDDEN_NAMES = new Set([
  'tfplan',
  'terraform.tfplan',
  'plan.out',
  'terraform.tfstate',
  'terraform.tfstate.backup',
])

const FORBIDDEN_SUFFIXES = ['.tfplan', '.tfstate', '.tfstate.backup']

/** Directories with nothing worth walking, and a great deal of it. */
const SKIP_DIRECTORIES = new Set(['.git', 'node_modules', '.next', '.turbo', '.venv', 'dist'])

export function isForbiddenArtifact(name: string): boolean {
  return FORBIDDEN_NAMES.has(name) || FORBIDDEN_SUFFIXES.some((s) => name.endsWith(s))
}

/** Every forbidden artifact under `root`, as paths relative to it. */
export function findForbiddenArtifacts(root: string): string[] {
  const found: string[] = []

  const walk = (directory: string): void => {
    let entries: string[]
    try {
      entries = readdirSync(directory)
    } catch {
      return
    }
    for (const entry of entries) {
      const full = join(directory, entry)
      let isDirectory: boolean
      try {
        isDirectory = statSync(full).isDirectory()
      } catch {
        continue
      }
      if (isDirectory) {
        if (!SKIP_DIRECTORIES.has(entry)) walk(full)
      } else if (isForbiddenArtifact(entry)) {
        found.push(relative(root, full).split(sep).join('/'))
      }
    }
  }

  walk(root)
  return found.sort()
}

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

/**
 * Commands that npm/corepack install as `.cmd` shims on Windows rather than as
 * real executables. Two Windows-only facts collide for these:
 *
 *   1. `spawn('pnpm', ...)` looks for a file named exactly `pnpm`. PATHEXT
 *      expansion only happens inside a shell, so the `pnpm.cmd` shim is never
 *      found and the call fails with `spawn pnpm ENOENT`.
 *   2. Naming the shim directly does not help either: Node refuses to spawn
 *      `.bat`/`.cmd` files unless `shell` is true (the CVE-2024-27980
 *      mitigation).
 *
 * `shell: true` is therefore the only combination that runs. It is safe for
 * these commands specifically because their argument lists are compile-time
 * literals and `cwd` is passed to spawn as an option, never interpolated into
 * a command line.
 *
 * `git` deliberately stays on `shell: false`: it is a real `git.exe` on every
 * platform, and its arguments carry a Terraform-supplied clone URL and a commit
 * message that must never reach a shell parser.
 */
const WINDOWS_SHELL_SHIMS = new Set(['pnpm', 'npm', 'npx', 'yarn', 'corepack'])

/** Exported for testing — the shim rule is platform-dependent and easy to regress. */
export function needsWindowsShell(
  cmd: string,
  platform: NodeJS.Platform = process.platform,
): boolean {
  return platform === 'win32' && WINDOWS_SHELL_SHIMS.has(cmd)
}

/** Anything cmd.exe would treat as syntax rather than as literal text. */
const SHELL_METACHARACTERS = /[&|<>^"'`$();\r\n]/

function spawnCmd(cmd: string, args: string[], cwd: string): Promise<number> {
  const shell = needsWindowsShell(cmd)

  // Node concatenates rather than escapes when `shell` is true, and warns about
  // it (DEP0190) if an args array is passed alongside. Build the command line
  // ourselves instead — but only after confirming every argument really is the
  // inert literal this path assumes, so a future caller cannot smuggle shell
  // syntax in through a command that happens to be on the shim list.
  if (shell) {
    const unsafe = args.find((arg) => SHELL_METACHARACTERS.test(arg))
    if (unsafe !== undefined) {
      return Promise.reject(
        new Error(
          `Refusing to run \`${cmd}\` through a shell with argument "${unsafe}": ` +
            `it contains shell metacharacters.`,
        ),
      )
    }
  }

  const command = shell ? [cmd, ...args].join(' ') : cmd
  const spawnArgs = shell ? [] : args

  return new Promise((resolve, reject) => {
    const child = spawn(command, spawnArgs, { cwd, stdio: 'inherit', shell })
    child.on('error', (err: Error) =>
      reject(
        new Error(
          `Could not run \`${cmd}\`: ${err.message}\n` +
            `  Ensure ${cmd} is installed and on PATH.`,
        ),
      ),
    )
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

    // Checked before `git add .`, not after. The commit is pushed moments
    // later, and a credential that reaches a remote is published whether or
    // not a later commit removes it.
    const forbidden = findForbiddenArtifacts(projectRoot)
    if (forbidden.length > 0) {
      throw new Error(
        [
          'Refusing to commit. These hold Terraform state, and state holds every',
          'credential Terraform touched:',
          '',
          ...forbidden.map((path) => '  ' + path),
          '',
          'Delete them and re-run. If any has already been pushed anywhere,',
          'rotate every secret it contained -- deleting a file does not',
          'unpublish it.',
        ].join('\n'),
      )
    }

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



