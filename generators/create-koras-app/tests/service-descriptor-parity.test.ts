import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, readdirSync, chmodSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { templatePath } from './template-path.js'

/**
 * The deploy workflow and Terraform decide, separately, whether a service
 * exists in an environment. They read the same file, and this holds them to the
 * same answer.
 *
 * Both are RUN here -- the workflow's discovery script, and the real
 * fly/eligibility module through `terraform apply` -- over one corpus of
 * descriptors, valid and not. Asserting that two rules are *written* alike
 * proves nothing; the two are in different languages and the cheap way for
 * them to drift is one being edited. So the claim tested is the behavioural
 * one: for every descriptor and every environment, the same services, and for
 * every invalid descriptor, both refuse.
 *
 * No provider is involved. The module declares none, so `terraform init` needs
 * no network and `apply` needs no credentials.
 *
 * In CI the tools are required, not optional: a skipped parity test is a green
 * check that means nothing.
 */

const ENVS = ['dev', 'test', 'stg', 'prod'] as const
const MODULE = join(__dirname, '..', '..', '..', 'infrastructure', 'terraform', 'modules', 'fly', 'eligibility')
const SCRIPT = templatePath('_shared', 'local', 'scripts', 'service-descriptor.sh')

function has(bin: string, args: string[] = ['--version']): boolean {
  return spawnSync(bin, args, { shell: false }).status === 0
}
const yqIsMikefarah = (() => {
  const r = spawnSync('yq', ['--version'], { encoding: 'utf8' })
  return r.status === 0 && /mikefarah/.test(r.stdout)
})()
const tools = has('bash') && has('jq') && has('terraform', ['version']) && yqIsMikefarah

if (process.env.CI && !tools) {
  describe('descriptor parity tooling', () => {
    it('needs bash, jq, mikefarah yq and terraform in CI', () => {
      expect.fail('bash, jq, yq (mikefarah) and terraform must all be installed in CI')
    })
  })
}

interface Case {
  name: string
  /** null: no descriptor file at all (the legacy case). */
  yaml: string | null
  valid: boolean
}

const OK = 'schema_version: 1\n'
const cases: Case[] = [
  { name: 'no descriptor (legacy)', yaml: null, valid: true },
  { name: 'dev only', yaml: `${OK}environments:\n  - dev\n`, valid: true },
  { name: 'dev and test', yaml: `${OK}environments: [dev, test]\n`, valid: true },
  { name: 'all four, flow style', yaml: `${OK}environments: [dev, test, stg, prod]\n`, valid: true },
  { name: 'prod only', yaml: `${OK}environments: [prod]\n`, valid: true },
  { name: 'environments omitted', yaml: `${OK}secrets:\n  policy: none\n`, valid: true },
  { name: 'only schema_version', yaml: OK, valid: true },
  { name: 'policy inherit', yaml: `${OK}secrets:\n  policy: inherit\n`, valid: true },
  { name: 'policy none', yaml: `${OK}secrets:\n  policy: none\n`, valid: true },
  { name: 'valid allowlist', yaml: `${OK}secrets:\n  policy: allowlist\n  allowlist: [DB_URL, API_KEY2]\n`, valid: true },
  { name: 'network private', yaml: `${OK}network: private\n`, valid: true },
  { name: 'network public', yaml: `${OK}network: public\n`, valid: true },
  {
    name: 'the clamd descriptor shape',
    yaml: `${OK}environments:\n  - dev\nsecrets:\n  policy: none\nnetwork: private\n`,
    valid: true,
  },

  { name: 'empty file', yaml: '', valid: false },
  { name: 'a list at the top', yaml: '- dev\n', valid: false },
  { name: 'a bare scalar', yaml: 'dev\n', valid: false },
  { name: 'schema_version missing', yaml: 'environments: [dev]\n', valid: false },
  { name: 'schema_version 2', yaml: 'schema_version: 2\n', valid: false },
  { name: 'schema_version as a string', yaml: 'schema_version: "1"\n', valid: false },
  { name: 'unknown top-level key', yaml: `${OK}colour: red\n`, valid: false },
  { name: 'environments empty', yaml: `${OK}environments: []\n`, valid: false },
  { name: 'environments a scalar', yaml: `${OK}environments: dev\n`, valid: false },
  { name: 'environments misspelt', yaml: `${OK}environments: [develop]\n`, valid: false },
  { name: 'environments wrong case', yaml: `${OK}environments: [Dev]\n`, valid: false },
  { name: 'environments duplicated', yaml: `${OK}environments: [dev, dev]\n`, valid: false },
  { name: 'environments a number', yaml: `${OK}environments: [1]\n`, valid: false },
  { name: 'environments a mapping', yaml: `${OK}environments:\n  dev: true\n`, valid: false },
  { name: 'unknown policy', yaml: `${OK}secrets:\n  policy: all\n`, valid: false },
  { name: 'policy a list', yaml: `${OK}secrets:\n  policy: [none]\n`, valid: false },
  { name: 'policy a boolean', yaml: `${OK}secrets:\n  policy: true\n`, valid: false },
  { name: 'secrets with no policy', yaml: `${OK}secrets: {}\n`, valid: false },
  { name: 'secrets a scalar', yaml: `${OK}secrets: none\n`, valid: false },
  { name: 'secrets unknown key', yaml: `${OK}secrets:\n  policy: none\n  extra: 1\n`, valid: false },
  { name: 'allowlist policy without a list', yaml: `${OK}secrets:\n  policy: allowlist\n`, valid: false },
  { name: 'allowlist empty', yaml: `${OK}secrets:\n  policy: allowlist\n  allowlist: []\n`, valid: false },
  { name: 'allowlist a scalar', yaml: `${OK}secrets:\n  policy: allowlist\n  allowlist: DB_URL\n`, valid: false },
  { name: 'allowlist lower case', yaml: `${OK}secrets:\n  policy: allowlist\n  allowlist: [db_url]\n`, valid: false },
  { name: 'allowlist a pattern', yaml: `${OK}secrets:\n  policy: allowlist\n  allowlist: ["DB_.*"]\n`, valid: false },
  { name: 'allowlist a glob', yaml: `${OK}secrets:\n  policy: allowlist\n  allowlist: ["DB_*"]\n`, valid: false },
  { name: 'allowlist DOPPLER_', yaml: `${OK}secrets:\n  policy: allowlist\n  allowlist: [DOPPLER_TOKEN]\n`, valid: false },
  { name: 'allowlist duplicated', yaml: `${OK}secrets:\n  policy: allowlist\n  allowlist: [A_B, A_B]\n`, valid: false },
  { name: 'allowlist entry a number', yaml: `${OK}secrets:\n  policy: allowlist\n  allowlist: [1]\n`, valid: false },
  { name: 'allowlist beside policy none', yaml: `${OK}secrets:\n  policy: none\n  allowlist: [A_B]\n`, valid: false },
  { name: 'allowlist beside policy inherit', yaml: `${OK}secrets:\n  policy: inherit\n  allowlist: [A_B]\n`, valid: false },
  { name: 'network unknown', yaml: `${OK}network: internet\n`, valid: false },
  { name: 'network a boolean', yaml: `${OK}network: true\n`, valid: false },
]

describe.skipIf(!tools)('the workflow and Terraform agree about every descriptor', () => {
  let work: string
  let harness: string

  // Service key `ai_gateway` -> directory `ai-gateway`: the mapping is part of
  // what must agree, and it is the one place a hyphen and an underscore meet.
  const KEY = 'ai_gateway'
  const DIR = 'ai-gateway'

  function sh(cmd: string, args: string[], cwd: string) {
    return spawnSync(cmd, args, { cwd, encoding: 'utf8', timeout: 120_000 })
  }

  function lay(yaml: string | null) {
    const services = join(work, 'services')
    rmSync(services, { recursive: true, force: true })
    for (const dir of ['api', DIR]) {
      mkdirSync(join(services, dir), { recursive: true })
      writeFileSync(join(services, dir, 'Dockerfile'), 'FROM scratch\n')
      writeFileSync(join(services, dir, 'fly.toml'), 'app = "x"\n')
    }
    // `api` never has a descriptor: it is the control, and must be in every
    // environment whatever its neighbour says.
    if (yaml !== null) writeFileSync(join(services, DIR, 'service.yaml'), yaml)
  }

  function workflowAnswer(): Record<string, string[]> | 'refused' {
    const out: Record<string, string[]> = {}
    for (const env of ENVS) {
      const r = sh('bash', [SCRIPT, 'eligible', env, 'services'], work)
      if (r.status !== 0) return 'refused'
      out[env] = (JSON.parse(r.stdout) as string[]).sort()
    }
    return out
  }

  function terraformAnswer(): Record<string, string[]> | 'refused' {
    for (const f of readdirSync(harness)) {
      if (f.startsWith('terraform.tfstate')) rmSync(join(harness, f), { force: true })
    }
    const apply = sh('terraform', ['apply', '-auto-approve', '-input=false', '-no-color'], harness)
    if (apply.status !== 0) {
      if (process.env.PARITY_DEBUG) console.log(apply.stdout + apply.stderr)
      return 'refused'
    }
    const o = sh('terraform', ['output', '-json', 'eligible'], harness)
    const raw = JSON.parse(o.stdout) as Record<string, string[]>
    const out: Record<string, string[]> = {}
    for (const env of ENVS) {
      // Terraform speaks in keys; the workflow in directories.
      out[env] = (raw[env] ?? []).map((k) => k.replace(/_/g, '-')).sort()
    }
    return out
  }

  beforeAll(() => {
    work = mkdtempSync(join(tmpdir(), 'koras-parity-'))
    harness = mkdtempSync(join(tmpdir(), 'koras-parity-tf-'))
    const modulePath = MODULE.replace(/\\/g, '/')
    const servicesDir = join(work, 'services').replace(/\\/g, '/')
    writeFileSync(
      join(harness, 'main.tf'),
      `module "e" {
  source       = "${modulePath}"
  services     = ["api", "${KEY}"]
  environments = ["dev", "test", "stg", "prod"]
  services_dir = "${servicesDir}"
}
output "eligible" { value = module.e.eligible }
`,
    )
    const init = sh('terraform', ['init', '-backend=false', '-input=false', '-no-color'], harness)
    expect(init.status, init.stderr + init.stdout).toBe(0)
  }, 120_000)

  afterAll(() => {
    rmSync(work, { recursive: true, force: true })
    rmSync(harness, { recursive: true, force: true })
  })

  it.each(cases)('$name', (c) => {
    lay(c.yaml)
    const wf = workflowAnswer()
    const tf = terraformAnswer()

    // The load-bearing assertion: whatever one says, the other says.
    expect(wf).toEqual(tf)

    if (!c.valid) {
      expect(wf, 'an invalid descriptor must be refused by both').toBe('refused')
      return
    }
    expect(wf).not.toBe('refused')
    const answer = wf as Record<string, string[]>
    // The control: a service with no descriptor is never affected.
    for (const env of ENVS) expect(answer[env]).toContain('api')
  }, 120_000)

  it('clamd: eligible in dev, nowhere else, from the descriptor the template ships', () => {
    lay(readFileSync(templatePath('product', 'services', 'clamd', 'service.yaml'), 'utf8'))
    const wf = workflowAnswer() as Record<string, string[]>
    const tf = terraformAnswer() as Record<string, string[]>
    expect(wf).toEqual(tf)
    expect(wf.dev).toContain(DIR)
    for (const env of ['test', 'stg', 'prod']) expect(wf[env]).not.toContain(DIR)
    for (const env of ENVS) expect(wf[env]).toContain('api')
  }, 120_000)
})

/**
 * Descriptors are opt-in, and so is the tool that reads them. A product with no
 * descriptor -- which is every product that has not asked for one -- must deploy
 * on a machine whose `yq` is missing or the wrong one, exactly as it did before
 * descriptors existed.
 */
describe.skipIf(!(has('bash') && has('jq')))('yq is needed only to read a descriptor that exists', () => {
  it('discovers services with a broken yq on PATH when none has a descriptor, and refuses when one does', () => {
    const work = mkdtempSync(join(tmpdir(), 'koras-noyq-'))
    try {
      const bin = join(work, 'bin')
      mkdirSync(bin)
      // A yq that is not mikefarah's, which is what an unrelated install looks like.
      writeFileSync(join(bin, 'yq'), '#!/usr/bin/env bash\necho "yq 3.4.1 (python)"\n')
      chmodSync(join(bin, 'yq'), 0o755)
      for (const dir of ['api', 'worker']) {
        mkdirSync(join(work, 'services', dir), { recursive: true })
        writeFileSync(join(work, 'services', dir, 'Dockerfile'), 'FROM scratch\n')
        writeFileSync(join(work, 'services', dir, 'fly.toml'), 'app = "x"\n')
      }
      const env = { ...process.env, PATH: `${bin}${process.platform === 'win32' ? ';' : ':'}${process.env.PATH}` }
      const legacy = spawnSync('bash', [SCRIPT, 'eligible', 'prod', 'services'], { cwd: work, encoding: 'utf8', env })
      expect(legacy.status, legacy.stderr).toBe(0)
      expect(JSON.parse(legacy.stdout)).toEqual(['api', 'worker'])

      writeFileSync(join(work, 'services', 'worker', 'service.yaml'), 'schema_version: 1\n')
      const withOne = spawnSync('bash', [SCRIPT, 'eligible', 'prod', 'services'], { cwd: work, encoding: 'utf8', env })
      expect(withOne.status).not.toBe(0)
      expect(withOne.stderr).toContain('mikefarah')
    } finally {
      rmSync(work, { recursive: true, force: true })
    }
  })
})
