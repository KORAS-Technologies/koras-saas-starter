import { describe, it, expect, afterAll } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { rmSync, existsSync, readFileSync } from 'node:fs'
import { SKIP_ENTRIES } from '../src/generation/skip.js'
import {
  digestInputs,
  digestOf,
  resolveTemplateDigest,
} from '../src/generation/project-manifest.js'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import { resolveSelections } from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'
import { writeFiles } from '../src/generation/writer.js'
import { validateGeneratedProject } from '../src/validation/generated-project.js'
import {
  CLAUDE_AGENTS,
  CLAUDE_COMMANDS,
  CLAUDE_CONFIG_PATHS,
  CLAUDE_PROFILE_SKILLS,
  EXTERNAL_SKILLS,
  KORAS_COMMON_SKILLS,
  claudeSkillPath,
} from '../src/validation/claude-config.js'

/**
 * Every generated repository must carry the common Koras Claude configuration
 * plus exactly one profile overlay.
 *
 * The overlay half is the part worth testing hardest. Common configuration
 * arriving is visible the moment anyone opens the project; the wrong overlay is
 * not — a product repository carrying control-plane instructions looks entirely
 * normal, and the first sign of it is an agent proposing a `platform_admin`
 * check in a customer-facing route.
 */

const OUT = join(tmpdir(), `koras-claude-${process.pid}-${Date.now()}`)

afterAll(() => {
  if (existsSync(OUT)) rmSync(OUT, { recursive: true, force: true })
})

function generate(profile: ProfileName, slug: string) {
  const { manifest, defaults } = loadProfile(profile)
  const ctx = buildContext({
    projectName: slug,
    projectSlug: slug,
    profile,
    manifest,
    defaults,
    selections: resolveSelections(manifest, defaults),
    outputDir: OUT,
    dryRun: false,
    provision: false,
  })
  const { fileList } = writeFiles(ctx, renderTemplate(ctx))
  const projectRoot = join(OUT, slug)
  return {
    slug,
    projectRoot,
    fileList,
    has: (path: string) => existsSync(join(projectRoot, path)),
    read: (path: string) => readFileSync(join(projectRoot, path), 'utf8'),
  }
}

const PRODUCT = generate('product', 'claude-product')
const CONTROL_PLANE = generate('control-plane', 'claude-cp')

const CASES: Array<[ProfileName, ReturnType<typeof generate>]> = [
  ['product', PRODUCT],
  ['control-plane', CONTROL_PLANE],
]

describe.each(CASES)('%s generation carries the common configuration', (profile, gen) => {
  it('writes .claude/CLAUDE.md', () => {
    expect(gen.has('.claude/CLAUDE.md')).toBe(true)
    // The shared instructions, not some other file that happens to share a name.
    expect(gen.read('.claude/CLAUDE.md')).toContain('Koras Engineering Instructions')
  })

  it('points Claude at .koras/project.yaml as the profile authority', () => {
    expect(gen.read('.claude/CLAUDE.md')).toContain('.koras/project.yaml')
    expect(gen.read('CLAUDE.md')).toContain('.koras/project.yaml')
  })

  it.each(KORAS_COMMON_SKILLS)('carries the %s skill', (skill) => {
    expect(gen.has(claudeSkillPath(skill))).toBe(true)
  })

  it.each(CLAUDE_COMMANDS)('carries the /%s command', (command) => {
    expect(gen.has(`.claude/commands/${command}.md`)).toBe(true)
  })

  it.each(CLAUDE_AGENTS)('carries the %s agent', (agent) => {
    expect(gen.has(`.claude/agents/${agent}.md`)).toBe(true)
  })

  it('carries the external-skill declaration, pinned rather than fetched', () => {
    // Generation must never reach the network for the standard configuration.
    expect(gen.has('.claude/external-skills.yaml')).toBe(true)
    expect(gen.has('.claude/scripts/sync-external-skills.mjs')).toBe(true)
  })

  it.each(EXTERNAL_SKILLS)('carries the vendored %s skill', (skill) => {
    // Vendored into the starter and committed, so a generated project has it
    // offline. A failure here means the starter's own sync was never run.
    expect(gen.has(claudeSkillPath(skill))).toBe(true)
  })

  it('records the profile in .koras/project.yaml', () => {
    expect(gen.read('.koras/project.yaml')).toContain(`profile: ${profile}`)
  })

  it('passes post-write validation', () => {
    const result = validateGeneratedProject({
      projectRoot: gen.projectRoot,
      expectedSlug: gen.slug,
      expectedProfile: profile,
    })
    expect(result.error).toBeUndefined()
    expect(result.valid).toBe(true)
  })
})

describe('exactly one profile overlay reaches each project', () => {
  it.each(CASES)('%s receives its own profile skill', (profile, gen) => {
    expect(gen.has(claudeSkillPath(CLAUDE_PROFILE_SKILLS[profile]))).toBe(true)
  })

  it('a product never receives control-plane instructions', () => {
    expect(PRODUCT.has(claudeSkillPath('koras-profile-control-plane'))).toBe(false)

    const claudeMd = PRODUCT.read('CLAUDE.md')
    expect(claudeMd).toContain('koras-profile-product')
    expect(claudeMd).not.toContain('koras-profile-control-plane')

    const overlays = PRODUCT.fileList.filter((f) => f.startsWith('.claude/skills/koras-profile'))
    expect(overlays).toHaveLength(1)

    // The substance, not the filename. The product skill may *name*
    // `platform_admin` to say it belongs elsewhere — that is the boundary being
    // drawn. What it must not do is carry the Control Plane's own mandates.
    const skill = PRODUCT.read(overlays[0])
    expect(skill).not.toContain('Never weaken `platform_admin`')
    expect(skill).not.toContain('Navigation visibility')
    expect(skill).toContain('Never trust a tenant identifier supplied by a browser')
    expect(skill).toMatch(/live in the KORAS Control Plane/)
  })

  it('the Control Plane never receives customer-product-only behaviour', () => {
    expect(CONTROL_PLANE.has(claudeSkillPath('koras-profile-product'))).toBe(false)

    const claudeMd = CONTROL_PLANE.read('CLAUDE.md')
    expect(claudeMd).toContain('koras-profile-control-plane')
    expect(claudeMd).not.toContain('koras-profile-product')

    const skill = CONTROL_PLANE.read(claudeSkillPath('koras-profile-control-plane'))
    expect(skill).toContain('never registers itself')
    expect(skill).toContain('platform_admin')
  })

  it('names the right profile skill in each generated CLAUDE.md routing table', () => {
    for (const [profile, gen] of CASES) {
      expect(gen.read('CLAUDE.md')).toContain(`.claude/skills/${CLAUDE_PROFILE_SKILLS[profile]}/`)
    }
  })
})

describe('the configuration is single-sourced, not duplicated per profile', () => {
  it('ships the common tree byte-identically to both profiles', () => {
    // The whole reason `.claude` is a shared_asset rather than two template
    // copies: a skill fixed in the starter is one edit, and the two profiles
    // cannot drift apart the way the template trees historically did.
    for (const path of [...KORAS_COMMON_SKILLS.map(claudeSkillPath), '.claude/CLAUDE.md']) {
      expect(CONTROL_PLANE.read(path)).toBe(PRODUCT.read(path))
    }
  })

  it('copies the starter tree verbatim, without Handlebars rendering', () => {
    const source = readFileSync(
      join(process.cwd(), '../../.claude/skills/koras-security/SKILL.md'),
      'utf8',
    )
    expect(PRODUCT.read(claudeSkillPath('koras-security'))).toBe(source)
  })

  it('holds no unrendered template tokens', () => {
    for (const [, gen] of CASES) {
      for (const path of gen.fileList.filter((f) => f.startsWith('.claude/'))) {
        expect(gen.read(path)).not.toMatch(/\{\{[a-zA-Z]/)
      }
      expect(gen.read('CLAUDE.md')).not.toMatch(/\{\{[a-zA-Z]/)
    }
  })

  it('declares every required path for a profile it knows', () => {
    // Guards the guard: an emptied CLAUDE_CONFIG_PATHS would leave every
    // validation above passing while checking nothing.
    expect(CLAUDE_CONFIG_PATHS.length).toBeGreaterThanOrEqual(17)
  })
})

describe('the template digest covers what a project actually receives', () => {
  // The hole this closes: `.claude` and infrastructure/terraform/modules both
  // reach a project as shared assets, and while the digest hashed only
  // profiles/<profile>/ a repository could be arbitrarily far behind on every
  // Koras skill and every Terraform module with its digest matching exactly.
  //
  // Asserted over the input list and a pure hash rather than by planting files
  // in the starter and re-hashing it. Vitest runs test files in parallel, so
  // the mutating version made an unrelated drift test report a difference that
  // did not exist -- and left junk behind when cleanup failed on Windows.

  const paths = (profile: ProfileName) => digestInputs(profile).map(([path]) => path)

  it.each(['product', 'control-plane'] as ProfileName[])(
    'includes the common Koras skills for %s',
    (profile) => {
      const seen = paths(profile)
      for (const skill of KORAS_COMMON_SKILLS) {
        expect(seen).toContain(`shared:.claude/${claudeSkillPath(skill).slice('.claude/'.length)}`)
      }
    },
  )

  it('includes the shared Terraform modules', () => {
    expect(paths('control-plane').some((p) => p.startsWith('shared:infrastructure/terraform/modules/'))).toBe(true)
  })

  it('still includes the profile tree', () => {
    expect(paths('product')).toContain('template/CLAUDE.md.hbs')
    expect(paths('product')).toContain('manifest.yaml')
  })

  it('namespaces shared assets so they cannot collide with profile paths', () => {
    // Every shared entry is prefixed; nothing from the profile tree is.
    const seen = paths('product')
    expect(seen.some((p) => p.startsWith('shared:'))).toBe(true)
    expect(seen).not.toContain('shared:manifest.yaml')
  })

  it('excludes what the engine excludes', () => {
    for (const profile of ['product', 'control-plane'] as ProfileName[]) {
      for (const p of paths(profile)) {
        const segments = p.replace(/^shared:/, '').split('/')
        expect(segments.some((segment) => SKIP_ENTRIES.has(segment))).toBe(false)
      }
    }
  })

  it('changes when any single input changes, and only then', () => {
    const base: Array<[string, Buffer]> = [
      ['a.md', Buffer.from('one')],
      ['b.md', Buffer.from('two')],
    ]
    const digest = digestOf(base)

    expect(digestOf([...base].reverse())).toBe(digest)          // order-independent
    expect(digestOf([['a.md', Buffer.from('one!')], base[1]])).not.toBe(digest)  // content
    expect(digestOf([['a2.md', base[0][1]], base[1]])).not.toBe(digest)          // rename
    expect(digestOf(base.slice(0, 1))).not.toBe(digest)                          // removal
  })

  it('is unchanged by CRLF line endings', () => {
    const CR = String.fromCharCode(13)
    const LF = String.fromCharCode(10)
    const lf = `alpha${LF}beta${LF}`
    const crlf = `alpha${CR}${LF}beta${CR}${LF}`
    // Guards the guard: prove the two forms genuinely differ as bytes, or the
    // assertion below would hold trivially.
    expect(Buffer.from(crlf).equals(Buffer.from(lf))).toBe(false)
    expect(digestOf([['x.md', Buffer.from(crlf)]])).toBe(digestOf([['x.md', Buffer.from(lf)]]))
  })

  it('gives the two profiles different digests', () => {
    // They share every shared asset, so an implementation that hashed only
    // those would collapse them into one value.
    expect(resolveTemplateDigest('product')).not.toBe(resolveTemplateDigest('control-plane'))
  })

  it('agrees with the digest the generator writes into a manifest', () => {
    for (const [profile, gen] of CASES) {
      expect(gen.read('.koras/project.yaml')).toContain(resolveTemplateDigest(profile))
    }
  })
})

describe('generated files name applications by directory, not by component key', () => {
  // The estate's rule, stated by the `basename` helper in engine.ts: a component
  // key is an internal manifest label, and the directory is the name. The
  // control-plane component `platform_admin` lives in `apps/admin`, and `admin`
  // is what names the Vercel project, the package and the deployment secret.
  //
  // `make profile` and CLAUDE.md's component table both print these for a
  // person to read, and both printed the component key -- a name nothing else
  // in the estate uses, and which does not match the directory the reader is
  // being pointed at.

  it('prints the directory name in the control-plane Makefile', () => {
    const makefile = CONTROL_PLANE.read('Makefile')
    expect(makefile).toContain('APPS := admin portal')

    // Asserted on the lines that name things, not on the whole file: the
    // comment above them names `platform_admin` deliberately, to explain why
    // the value below it is not that.
    const naming = makefile
      .split('\n')
      .map((line) => line.replace('\r', ''))
      .filter((line) => line.startsWith('APPS :=') || line.startsWith('# Applications:'))
    expect(naming).toHaveLength(2)
    for (const line of naming) expect(line).not.toContain('platform_admin')
  })

  it('prints the directory name in the control-plane CLAUDE.md table', () => {
    const claudeMd = CONTROL_PLANE.read('CLAUDE.md')
    expect(claudeMd).toMatch(/\| Applications \|.*`admin`.*`portal`/)
    expect(claudeMd).not.toContain('`platform_admin`')
  })

  it('names a directory that the project actually has', () => {
    // The point of the rule: the printed name resolves to a real path.
    for (const [, gen] of CASES) {
      const apps = /APPS := (.*)/.exec(gen.read('Makefile'))?.[1]?.trim().split(/\s+/) ?? []
      expect(apps.length).toBeGreaterThan(0)
      for (const app of apps) {
        expect(gen.has(`apps/${app}`)).toBe(true)
      }
    }
  })

  it('does the same for services', () => {
    for (const [, gen] of CASES) {
      const services = /SERVICES := (.*)/.exec(gen.read('Makefile'))?.[1]?.trim().split(/\s+/) ?? []
      for (const service of services) {
        expect(gen.has(`services/${service}`)).toBe(true)
      }
    }
  })
})
