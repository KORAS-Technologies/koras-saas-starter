import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { rmSync, existsSync, readFileSync } from 'node:fs'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import { resolveSelections } from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'
import { writeFiles } from '../src/generation/writer.js'

const TEST_OUTPUT = join(tmpdir(), `koras-gen-test-${Date.now()}`)

afterAll(() => {
  if (existsSync(TEST_OUTPUT)) rmSync(TEST_OUTPUT, { recursive: true })
})

function makeCtx(profile: ProfileName, slug: string, dryRun = false) {
  const { manifest, defaults } = loadProfile(profile)
  const selections = resolveSelections(manifest, defaults)
  return buildContext({
    projectName: slug,
    projectSlug: slug,
    profile,
    manifest,
    defaults,
    selections,
    outputDir: TEST_OUTPUT,
    dryRun,
    provision: false,
  })
}

// ── dry-run writes nothing ───────────────────────────────────────────────────

describe('dry-run', () => {
  it('returns file list without writing', () => {
    const ctx = makeCtx('product', 'drytest', true)
    const files = renderTemplate(ctx)
    const result = writeFiles(ctx, files)
    expect(result.filesWritten).toBe(0)
    expect(result.fileList.length).toBeGreaterThan(0)
    expect(existsSync(join(TEST_OUTPUT, 'drytest'))).toBe(false)
  })
})

// ── product profile generation ───────────────────────────────────────────────

describe('generate product', () => {
  let fileList: string[]

  beforeAll(() => {
    const ctx = makeCtx('product', 'testproduct')
    const files = renderTemplate(ctx)
    const result = writeFiles(ctx, files)
    fileList = result.fileList
  })

  it('generates files', () => {
    expect(fileList.length).toBeGreaterThan(10)
  })

  it('generates Makefile', () => {
    expect(fileList.some((f) => f === 'Makefile')).toBe(true)
  })

  it('generates apps/web', () => {
    expect(fileList.some((f) => f.startsWith('apps/web/'))).toBe(true)
  })

  it('generates services/api', () => {
    expect(fileList.some((f) => f.startsWith('services/api/'))).toBe(true)
  })

  it('generates supabase migration', () => {
    expect(fileList.some((f) => f.includes('migrations/00001_initial.sql'))).toBe(true)
  })

  it('does NOT generate apps/admin (platform-admin variant)', () => {
    // product admin is apps/admin not apps/platform-admin
    expect(fileList.some((f) => f.startsWith('apps/portal/'))).toBe(false)
  })

  it('renders project slug into package.json', () => {
    const outputPath = join(TEST_OUTPUT, 'testproduct', 'package.json')
    expect(existsSync(outputPath)).toBe(true)
    const content = readFileSync(outputPath, 'utf8')
    expect(content).toContain('testproduct')
  })
})

// ── control-plane profile generation ────────────────────────────────────────

describe('generate control-plane', () => {
  let fileList: string[]

  beforeAll(() => {
    const ctx = makeCtx('control-plane', 'testcp')
    const files = renderTemplate(ctx)
    const result = writeFiles(ctx, files)
    fileList = result.fileList
  })

  it('generates apps/admin (platform-admin)', () => {
    expect(fileList.some((f) => f.startsWith('apps/admin/'))).toBe(true)
  })

  it('generates apps/portal', () => {
    expect(fileList.some((f) => f.startsWith('apps/portal/'))).toBe(true)
  })

  it('generates services/api', () => {
    expect(fileList.some((f) => f.startsWith('services/api/'))).toBe(true)
  })

  it('generates services/worker', () => {
    expect(fileList.some((f) => f.startsWith('services/worker/'))).toBe(true)
  })

  it('generates services/scheduler', () => {
    expect(fileList.some((f) => f.startsWith('services/scheduler/'))).toBe(true)
  })

  it('does NOT generate apps/web', () => {
    expect(fileList.some((f) => f.startsWith('apps/web/'))).toBe(false)
  })

  it('does NOT generate apps/marketing', () => {
    expect(fileList.some((f) => f.startsWith('apps/marketing/'))).toBe(false)
  })

  it('does NOT generate services/ai-gateway', () => {
    expect(fileList.some((f) => f.startsWith('services/ai-gateway/'))).toBe(false)
  })

  it('generates platform schema migration', () => {
    expect(fileList.some((f) => f.includes('migrations/00001_initial.sql'))).toBe(true)
  })

  it('renders project slug into package.json', () => {
    const outputPath = join(TEST_OUTPUT, 'testcp', 'package.json')
    expect(existsSync(outputPath)).toBe(true)
    const content = readFileSync(outputPath, 'utf8')
    expect(content).toContain('testcp')
  })
})
