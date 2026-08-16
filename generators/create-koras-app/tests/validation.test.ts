import { describe, it, expect } from 'vitest'
import { validateSlug, deriveSlug } from '../src/validation/slug.js'
import { validateProfile } from '../src/validation/profile.js'
import { checkDirectoryConflict } from '../src/validation/conflicts.js'
import { tmpdir } from 'node:os'
import { join, basename } from 'node:path'
import { mkdirSync, rmSync } from 'node:fs'

// ── slug ────────────────────────────────────────────────────────────────────

describe('validateSlug', () => {
  it('accepts valid slugs', () => {
    expect(validateSlug('docoris').valid).toBe(true)
    expect(validateSlug('my-app').valid).toBe(true)
    expect(validateSlug('koras-control-plane').valid).toBe(true)
    expect(validateSlug('app123').valid).toBe(true)
  })

  it('rejects slugs that are too short', () => {
    expect(validateSlug('a').valid).toBe(false)
  })

  it('rejects slugs with uppercase', () => {
    expect(validateSlug('MyApp').valid).toBe(false)
  })

  it('rejects slugs with underscores', () => {
    expect(validateSlug('my_app').valid).toBe(false)
  })

  it('rejects slugs with consecutive hyphens', () => {
    expect(validateSlug('my--app').valid).toBe(false)
  })

  it('rejects reserved words', () => {
    expect(validateSlug('koras').valid).toBe(false)
    expect(validateSlug('admin').valid).toBe(false)
    expect(validateSlug('api').valid).toBe(false)
  })

  it('provides a suggestion for invalid slugs', () => {
    const result = validateSlug('MyApp')
    expect(result.suggestion).toBeDefined()
  })
})

describe('deriveSlug', () => {
  it('lowercases and replaces spaces', () => {
    expect(deriveSlug('My App')).toBe('my-app')
  })

  it('collapses multiple hyphens', () => {
    expect(deriveSlug('my--app')).toBe('my-app')
  })

  it('strips leading and trailing hyphens', () => {
    expect(deriveSlug('-myapp-')).toBe('myapp')
  })
})

// ── profile ─────────────────────────────────────────────────────────────────

describe('validateProfile', () => {
  it('accepts product', () => {
    expect(validateProfile('product').valid).toBe(true)
  })

  it('accepts control-plane', () => {
    expect(validateProfile('control-plane').valid).toBe(true)
  })

  it('rejects unknown profile', () => {
    const result = validateProfile('saas')
    expect(result.valid).toBe(false)
    expect(result.error).toMatch(/unknown profile/i)
  })

  it('rejects empty string with helpful message', () => {
    const result = validateProfile('')
    expect(result.valid).toBe(false)
    expect(result.error).toMatch(/required/i)
  })
})

// ── conflicts ────────────────────────────────────────────────────────────────

describe('checkDirectoryConflict', () => {
  it('returns no conflict when directory does not exist', () => {
    const result = checkDirectoryConflict(tmpdir(), 'koras-test-nonexistent-xyz')
    expect(result.conflict).toBe(false)
  })

  it('detects existing directory', () => {
    const testDir = join(tmpdir(), `koras-test-${Date.now()}`)
    mkdirSync(testDir)
    try {
      const result = checkDirectoryConflict(tmpdir(), basename(testDir))
      expect(result.conflict).toBe(true)
      expect(result.message).toMatch(/already exists/i)
    } finally {
      rmSync(testDir, { recursive: true })
    }
  })
})
