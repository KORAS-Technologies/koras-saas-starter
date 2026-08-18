import { existsSync, readFileSync, mkdtempSync, writeFileSync, rmSync, cpSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { DoctorCheck, DoctorContext, DoctorResult } from '../types.js'
import { value } from '../env.js'

/**
 * Terraform readiness: the binary exists, it satisfies the version the modules
 * declare, the shared module tree is valid, and — because the generated
 * backend is HCP Terraform — a token for app.terraform.io is present.
 *
 * `init` runs with `-backend=false`, so no state is touched and no backend is
 * contacted. `validate` reads configuration only. `apply`, `destroy`, and
 * `import` are never reachable from here.
 *
 * The configuration is assembled in a temporary directory rather than
 * validated in place, for two reasons. `project-bootstrap` cannot be validated
 * on its own — it declares provider aliases (`zitadel.dev` … `zitadel.prod`)
 * that its caller must pass in, so a standalone validate fails with a missing
 * provider that is not actually missing. And a doctor command should leave no
 * trace: initializing in the repository would drop `.terraform/` and
 * `.terraform.lock.hcl` into the working tree.
 *
 * The temporary root is the repository's own `templates/*.tpl`, which are valid
 * HCL, over a copy of the modules tree — the same shape a generated project
 * gets, so this validates what will actually be provisioned.
 */

const ROOT_MODULE = 'project-bootstrap'

/** Root files that make a valid configuration. backend.tf is not one of them: */
/** it carries generator placeholders, and `-backend=false` does not need it. */
const ROOT_TEMPLATES = ['main.tf.tpl', 'providers.tf.tpl', 'variables.tf.tpl']

export function modulesDirectory(repoRoot: string): string {
  return join(repoRoot, 'infrastructure', 'terraform', 'modules')
}

/** The minimum version the modules themselves declare — not hard-coded here. */
export function requiredVersion(repoRoot: string): string | undefined {
  const providers = join(modulesDirectory(repoRoot), ROOT_MODULE, 'providers.tf')
  if (!existsSync(providers)) return undefined
  return /required_version\s*=\s*">=\s*([\d.]+)"/.exec(readFileSync(providers, 'utf8'))?.[1]
}

export function parseVersion(output: string): string | undefined {
  try {
    const parsed = JSON.parse(output) as { terraform_version?: unknown }
    if (typeof parsed.terraform_version === 'string') return parsed.terraform_version
  } catch {
    // `terraform version` without -json, or an older binary.
  }
  return /Terraform v(\d+\.\d+\.\d+)/.exec(output)?.[1]
}

/** Numeric comparison — "1.10" must sort above "1.6", which a string compare gets wrong. */
export function satisfies(actual: string, minimum: string): boolean {
  const a = actual.split('.').map(Number)
  const b = minimum.split('.').map(Number)
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const left = a[i] ?? 0
    const right = b[i] ?? 0
    if (left !== right) return left > right
  }
  return true
}

/** Whether the generated configuration uses HCP Terraform for state. */
export function usesTerraformCloud(repoRoot: string): boolean {
  const candidates = [
    join(repoRoot, 'profiles', 'product', 'template', 'infrastructure', 'terraform', 'backend.tf.hbs'),
    join(repoRoot, 'profiles', 'control-plane', 'template', 'infrastructure', 'terraform', 'backend.tf.hbs'),
    join(repoRoot, 'infrastructure', 'terraform', 'templates', 'backend.tf.tpl'),
  ]
  return candidates.some(
    (path) => existsSync(path) && /backend\s+"remote"|cloud\s*\{/.test(readFileSync(path, 'utf8')),
  )
}

export async function checkTerraform(ctx: DoctorContext): Promise<DoctorResult> {
  const modules = modulesDirectory(ctx.repoRoot)
  if (!existsSync(modules)) {
    return { passed: false, error: `No Terraform modules found at ${modules}.` }
  }

  // ── binary and version ─────────────────────────────────────────────────────

  let versionOutput
  try {
    versionOutput = await ctx.exec('terraform', ['version', '-json'], {
      cwd: ctx.repoRoot,
      env: ctx.env,
    })
  } catch {
    return {
      passed: false,
      error: 'terraform is not installed or not on PATH.\nSee https://developer.hashicorp.com/terraform/install',
    }
  }

  if (versionOutput.exitCode !== 0) {
    return { passed: false, error: 'terraform version failed.' }
  }

  const installed = parseVersion(versionOutput.stdout)
  if (!installed) return { passed: false, error: 'Could not determine the installed Terraform version.' }

  const minimum = requiredVersion(ctx.repoRoot)
  if (minimum && !satisfies(installed, minimum)) {
    return {
      passed: false,
      error: `Terraform ${installed} is installed; the modules require >= ${minimum}.`,
    }
  }

  // ── HCP Terraform credential ───────────────────────────────────────────────
  // Required only because the generated backend is "remote". If the repository
  // ever moves off HCP, this stops being required rather than failing.

  if (usesTerraformCloud(ctx.repoRoot)) {
    const token =
      value(ctx.env, 'TF_TOKEN_app_terraform_io') ?? value(ctx.env, 'TF_TOKEN_APP_TERRAFORM_IO')
    if (!token) {
      return {
        passed: false,
        error:
          'TF_TOKEN_APP_TERRAFORM_IO is not set, and the generated backend is HCP Terraform.\n' +
          'Set it, or run `terraform login`.',
      }
    }
  }

  // ── configuration validity ─────────────────────────────────────────────────

  if (!existsSync(join(modules, ROOT_MODULE))) {
    return { passed: false, error: `Module "${ROOT_MODULE}" not found under ${modules}.` }
  }

  let root: string
  try {
    root = writeTemporaryRoot(ctx.repoRoot)
  } catch (err) {
    return { passed: false, error: (err as Error).message }
  }

  try {
    const init = await ctx.exec(
      'terraform',
      ['init', '-backend=false', '-input=false', '-no-color'],
      { cwd: root, env: ctx.env },
    )
    if (init.exitCode !== 0) {
      return {
        passed: false,
        error: `terraform init failed.\n${firstLines(init.stderr || init.stdout)}`,
      }
    }

    const validate = await ctx.exec('terraform', ['validate', '-no-color'], {
      cwd: root,
      env: ctx.env,
    })
    if (validate.exitCode !== 0) {
      return {
        passed: false,
        error: `terraform validate failed.\n${firstLines(validate.stderr || validate.stdout)}`,
      }
    }
  } finally {
    rmSync(root, { recursive: true, force: true })
  }

  return { passed: true }
}

/**
 * Materialises a root configuration in a temporary directory and returns its
 * path. The caller removes it.
 */
export function writeTemporaryRoot(repoRoot: string): string {
  const templates = join(repoRoot, 'infrastructure', 'terraform', 'templates')
  const modules = modulesDirectory(repoRoot)
  const root = mkdtempSync(join(tmpdir(), 'koras-doctor-'))

  for (const template of ROOT_TEMPLATES) {
    const source = join(templates, template)
    if (!existsSync(source)) {
      rmSync(root, { recursive: true, force: true })
      throw new Error(`Root template ${template} is missing from ${templates}.`)
    }
    writeFileSync(join(root, template.replace(/\.tpl$/, '')), readFileSync(source, 'utf8'), 'utf8')
  }

  // The modules are copied rather than referenced in place. Terraform refuses a
  // local module whose own relative sources escape its package, and
  // project-bootstrap reaches its siblings with `../zitadel` — which only
  // resolves when the whole tree sits under the root, exactly as it does in a
  // generated project.
  cpSync(modules, join(root, 'modules'), { recursive: true })

  return root
}

/** Keeps the failure section short; the full output is not worth printing. */
function firstLines(output: string, count = 4): string {
  return output.trim().split('\n').slice(0, count).join('\n')
}

export const terraformCheck: DoctorCheck = { label: 'Terraform', run: checkTerraform }
