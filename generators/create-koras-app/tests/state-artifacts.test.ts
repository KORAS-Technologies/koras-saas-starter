import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { mkdirSync, rmSync, existsSync, writeFileSync, readFileSync } from 'node:fs'
import {
  findForbiddenArtifacts,
  initAndPushToDevelop,
  isForbiddenArtifact,
  type CommandExecutor,
} from '../src/git.js'

/**
 * A Terraform plan embeds a full state snapshot -- every credential Terraform
 * touched, including database passwords and OIDC client secrets it generated.
 * The generator wrote one into the project it had just created and then ran
 * `git add .` and pushed, so every `--provision` run published its estate's
 * credentials to GitHub.
 *
 * It was silent because content scanners cannot see these. gitleaks decides
 * whether to look inside an archive from the file extension, and a plan file
 * has none. Measured on a real one: `tfplan` scans as zero bytes and reports
 * nothing, while the byte-identical file named `tfplan.zip` yields 28 findings.
 *
 * Three defences, tested here: the plan is written outside the project, the
 * template .gitignore names it, and the commit step refuses outright.
 */

const ROOT = join(tmpdir(), `koras-artifacts-${process.pid}-${Date.now()}`)

beforeEach(() => mkdirSync(ROOT, { recursive: true }))
afterEach(() => {
  if (existsSync(ROOT)) rmSync(ROOT, { recursive: true, force: true })
})

function makeProjectDir(name: string): string {
  const dir = join(ROOT, name)
  mkdirSync(dir, { recursive: true })
  writeFileSync(join(dir, 'README.md'), `# ${name}`)
  return dir
}

describe('isForbiddenArtifact', () => {
  it.each([
    'tfplan',
    'terraform.tfplan',
    'plan.out',
    'terraform.tfstate',
    'terraform.tfstate.backup',
    'anything.tfplan',
    'staging.tfstate',
  ])('rejects %s', (name) => {
    expect(isForbiddenArtifact(name)).toBe(true)
  })

  it.each(['main.tf', 'terraform.tfvars', '.terraform.lock.hcl', 'variables.tf', 'plan.md'])(
    'permits %s',
    (name) => {
      // A rule that also blocked ordinary Terraform would be deleted within the
      // week, and then it would protect nothing.
      expect(isForbiddenArtifact(name)).toBe(false)
    },
  )
})

describe('findForbiddenArtifacts', () => {
  it('finds one nested inside the project', () => {
    const projectRoot = makeProjectDir('nested')
    mkdirSync(join(projectRoot, 'infrastructure', 'terraform'), { recursive: true })
    writeFileSync(join(projectRoot, 'infrastructure', 'terraform', 'tfplan'), 'PK')

    expect(findForbiddenArtifacts(projectRoot)).toEqual(['infrastructure/terraform/tfplan'])
  })

  it('reports nothing for a clean project', () => {
    const projectRoot = makeProjectDir('clean')
    mkdirSync(join(projectRoot, 'infrastructure', 'terraform'), { recursive: true })
    writeFileSync(join(projectRoot, 'infrastructure', 'terraform', 'main.tf'), 'locals {}')

    expect(findForbiddenArtifacts(projectRoot)).toEqual([])
  })

  it('does not walk into node_modules', () => {
    // Not an optimisation. A dependency shipping a fixture named tfplan would
    // otherwise block every commit, and the check would be turned off.
    const projectRoot = makeProjectDir('with-deps')
    mkdirSync(join(projectRoot, 'node_modules', 'some-package'), { recursive: true })
    writeFileSync(join(projectRoot, 'node_modules', 'some-package', 'tfplan'), 'fixture')

    expect(findForbiddenArtifacts(projectRoot)).toEqual([])
  })
})

describe('initAndPushToDevelop', () => {
  it('refuses to commit a project containing a plan file', async () => {
    const projectRoot = makeProjectDir('leaky')
    mkdirSync(join(projectRoot, 'infrastructure', 'terraform'), { recursive: true })
    writeFileSync(join(projectRoot, 'infrastructure', 'terraform', 'tfplan'), 'PK')

    const calls: Array<{ cmd: string; args: string[] }> = []
    const exec: CommandExecutor = (cmd, args) => {
      calls.push({ cmd, args })
      return Promise.resolve(0)
    }

    await expect(
      initAndPushToDevelop({
        projectRoot,
        repositoryFullName: 'KORAS-Technologies/leaky',
        exec,
      }),
    ).rejects.toThrow(/Refusing to commit/)

    // Nothing was staged, committed or pushed. Refusing after `git add` would
    // still leave the artifact one `git commit` away.
    expect(calls.some((c) => c.args[0] === 'add')).toBe(false)
    expect(calls.some((c) => c.args[0] === 'push')).toBe(false)
  })

  it('says to rotate, not merely to delete', async () => {
    // Deleting the file does not unpublish what was already pushed. A message
    // that only says "remove it" leaves the credentials live.
    const projectRoot = makeProjectDir('advice')
    writeFileSync(join(projectRoot, 'terraform.tfstate'), '{}')

    await expect(
      initAndPushToDevelop({
        projectRoot,
        repositoryFullName: 'KORAS-Technologies/advice',
        exec: () => Promise.resolve(0),
      }),
    ).rejects.toThrow(/rotate/)
  })
})

describe('the generated .gitignore', () => {
  it.each(['control-plane', 'product'])('names plan files for the %s profile', (profile) => {
    // Second line of defence. The plan is written outside the project now, so
    // this should never be load-bearing -- which is the point of having it.
    const template = readFileSync(
      join(__dirname, '..', '..', '..', 'profiles', profile, 'template', '.gitignore.hbs'),
      'utf8',
    )
    expect(template).toMatch(/^tfplan$/m)
    expect(template).toMatch(/^\*\.tfplan$/m)
  })
})
