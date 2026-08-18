import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import { resolveSelections } from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { vercelProjectNames, flyAppNames } from '../src/generation/context.js'

function ctxFor(profile: ProfileName, slug: string, overrides: Record<string, boolean> = {}) {
  const { manifest, defaults } = loadProfile(profile)
  const selections = resolveSelections(manifest, defaults)
  Object.assign(selections.applications, overrides)
  Object.assign(selections.services, overrides)
  return buildContext({
    projectName: slug,
    projectSlug: slug,
    profile,
    manifest,
    defaults,
    selections,
    outputDir: '.',
    dryRun: true,
    provision: false,
  })
}

// Vercel and Fly both reject underscores in resource names, and reject them at
// plan time — after other providers have already created resources. Component
// keys are identifiers, so `platform_admin` and `ai_gateway` are legal keys and
// illegal names.
describe('resource names never carry an underscore', () => {
  it('hyphenates control-plane Vercel project names', () => {
    const names = vercelProjectNames(ctxFor('control-plane', 'koras-control-plane'))
    expect(names).toContain('koras-control-plane-platform-admin')
    for (const name of names) expect(name).not.toContain('_')
  })

  it('hyphenates the AI Gateway in Fly app names', () => {
    const names = flyAppNames(ctxFor('product', 'docoris', { ai_gateway: true }))
    expect(names).toContain('docoris-ai-gateway-dev')
    for (const name of names) expect(name).not.toContain('_')
  })

  it('leaves keys that need no change untouched', () => {
    expect(vercelProjectNames(ctxFor('product', 'docoris'))).toContain('docoris-web')
  })
})

describe('the Terraform modules hyphenate too', () => {
  const modules = join(process.cwd(), '../../infrastructure/terraform/modules')

  it('sanitizes in the Vercel module, not just in the generator', () => {
    // The generator only names things for the README and the registration
    // payload; Terraform is what actually creates them. Both must agree.
    const main = readFileSync(join(modules, 'vercel', 'main.tf'), 'utf8')
    expect(main).toMatch(/replace\(app, "_", "-"\)/)
    expect(main).not.toMatch(/name\s+= "\$\{var\.project_slug\}-\$\{each\.key\}"/)
  })

  it('sanitizes in the Fly module', () => {
    const main = readFileSync(join(modules, 'fly', 'main.tf'), 'utf8')
    expect(main).toMatch(/replace\(each\.value\.service, "_", "-"\)/)
  })
})
