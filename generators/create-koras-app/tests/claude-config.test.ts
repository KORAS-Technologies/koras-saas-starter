import { describe, it, expect, afterAll } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { rmSync, existsSync, readFileSync, writeFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { SKIP_ENTRIES } from '../src/generation/skip.js'
import {
  normalizeForDigest,
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

describe('the template digest describes content, not the checkout', () => {
  it('is unchanged by CRLF line endings', () => {
    // `.gitattributes` sets `* text=auto`, so every profile template file is LF
    // in the object store and CRLF in a Windows working tree. Hashing raw bytes
    // therefore gave CI and a Windows machine different digests for the same
    // profile, and a digest written before a merge stopped matching after it --
    // the checkout had rewritten the files being hashed.
    const CR = String.fromCharCode(13)
    const LF = String.fromCharCode(10)

    const sample = readFileSync(
      join(process.cwd(), '../../profiles/product/template/CLAUDE.md.hbs'),
      'utf8',
    )
    // Guards the guard: on a checkout that is already LF the assertion below
    // would hold trivially, so prove the two forms genuinely differ as bytes.
    const asLf = sample.split(CR + LF).join(LF)
    const asCrlf = asLf.split(LF).join(CR + LF)
    expect(Buffer.from(asCrlf).equals(Buffer.from(asLf))).toBe(false)

    const digest = (text: string) =>
      createHash('sha256').update(normalizeForDigest(Buffer.from(text))).digest('hex')
    expect(digest(asCrlf)).toBe(digest(asLf))
  })

  it('still distinguishes a real content change', () => {
    const digest = (text: string) =>
      createHash('sha256').update(normalizeForDigest(Buffer.from(text))).digest('hex')
    expect(digest('a' + String.fromCharCode(10))).not.toBe(digest('b' + String.fromCharCode(10)))
  })

  it('agrees with the digest the generator writes into a manifest', () => {
    for (const [profile, gen] of CASES) {
      expect(gen.read('.koras/project.yaml')).toContain(resolveTemplateDigest(profile))
    }
  })
})

describe('the template digest covers what a project actually receives', () => {
  // The hole this closes: `.claude` and infrastructure/terraform/modules both
  // reach a project as shared assets, and while the digest hashed only
  // profiles/<profile>/ a repository could be arbitrarily far behind on every
  // Koras skill and every Terraform module with its digest matching exactly.
  const STARTER = join(process.cwd(), '../..')

  function withTempFile<T>(relPath: string, body: () => T): T {
    const target = join(STARTER, relPath)
    expect(existsSync(target)).toBe(false)
    writeFileSync(target, 'temporary probe\n', 'utf8')
    try {
      return body()
    } finally {
      rmSync(target, { force: true })
    }
  }

  it('changes when a common Koras skill changes', () => {
    const before = resolveTemplateDigest('product')
    const after = withTempFile('.claude/skills/koras-architecture/PROBE.md', () =>
      resolveTemplateDigest('product'),
    )
    expect(after).not.toBe(before)
    expect(resolveTemplateDigest('product')).toBe(before)
  })

  it('changes when a shared Terraform module changes', () => {
    const before = resolveTemplateDigest('control-plane')
    const after = withTempFile('infrastructure/terraform/modules/PROBE.tf', () =>
      resolveTemplateDigest('control-plane'),
    )
    expect(after).not.toBe(before)
  })

  it('still changes when the profile tree changes', () => {
    const before = resolveTemplateDigest('product')
    const after = withTempFile('profiles/product/template/PROBE.txt', () =>
      resolveTemplateDigest('product'),
    )
    expect(after).not.toBe(before)
  })

  it('gives the two profiles different digests', () => {
    // They share every shared asset, so an implementation that hashed only
    // those would collapse them into one value.
    expect(resolveTemplateDigest('product')).not.toBe(resolveTemplateDigest('control-plane'))
  })

  it('is stable across repeated computation', () => {
    expect(resolveTemplateDigest('product')).toBe(resolveTemplateDigest('product'))
  })

  it('shares its skip rules with the engine, rather than restating them', () => {
    // A digest that hashed a local .terraform provider cache would differ on
    // every machine and report every project as stale. That is guaranteed
    // structurally: the digest walks with the same SKIP_ENTRIES the engine
    // copies with, so the two cannot disagree about what a project receives.
    //
    // Asserted as a shared constant rather than by planting a cache in the
    // starter and hashing it. That version wrote into a gitignored directory
    // in the real repository, and a cleanup that failed on Windows left the
    // junk behind invisibly -- reproducing the exact defect it guarded against.
    // refresh.test.ts already proves the engine excludes these.
    expect(SKIP_ENTRIES.has('.terraform')).toBe(true)
    expect(SKIP_ENTRIES.has('.terraform.lock.hcl')).toBe(true)
    expect(SKIP_ENTRIES.has('node_modules')).toBe(true)
  })
})
