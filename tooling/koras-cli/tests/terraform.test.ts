import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import {
  parseVersion,
  satisfies,
  requiredVersion,
  usesTerraformCloud,
  writeTemporaryRoot,
} from '../src/doctor/checks/terraform.js'
import { terraformOrganization } from '../src/doctor/checks/terraform-state.js'
import { REPO_ROOT } from './helpers.js'

describe('version parsing', () => {
  it('reads the JSON form', () => {
    expect(parseVersion('{"terraform_version":"1.15.8"}')).toBe('1.15.8')
  })

  it('falls back to the human-readable form', () => {
    expect(parseVersion('Terraform v1.9.2\non windows_amd64')).toBe('1.9.2')
  })

  it('returns undefined when the output says nothing useful', () => {
    expect(parseVersion('command not found')).toBeUndefined()
  })
})

describe('version comparison', () => {
  it('compares numerically, not lexically', () => {
    // The case a string compare gets wrong: "1.10" < "1.6" as text.
    expect(satisfies('1.10.0', '1.6')).toBe(true)
    expect(satisfies('1.6.0', '1.6')).toBe(true)
    expect(satisfies('1.5.9', '1.6')).toBe(false)
    expect(satisfies('2.0.0', '1.6')).toBe(true)
  })
})

describe('repository configuration', () => {
  it('reads the minimum version from the modules, not a constant', () => {
    expect(requiredVersion(REPO_ROOT)).toBe('1.6')
  })

  it('detects that the generated backend is HCP Terraform', () => {
    expect(usesTerraformCloud(REPO_ROOT)).toBe(true)
  })

  it('reads the HCP organization from the profile defaults', () => {
    expect(terraformOrganization(REPO_ROOT)).toBe('koras')
  })

  it('reports no organization when the profiles are elsewhere', () => {
    expect(terraformOrganization(join(REPO_ROOT, 'does-not-exist'))).toBeUndefined()
  })
})

describe('temporary validation root', () => {
  it('assembles a root outside the repository and copies the modules', () => {
    const root = writeTemporaryRoot(REPO_ROOT)
    try {
      expect(root.startsWith(REPO_ROOT)).toBe(false)
      for (const file of ['main.tf', 'providers.tf', 'variables.tf']) {
        expect(existsSync(join(root, file))).toBe(true)
      }
      // backend.tf carries generator placeholders and must not be written.
      expect(existsSync(join(root, 'backend.tf'))).toBe(false)
      expect(readFileSync(join(root, 'main.tf'), 'utf8')).not.toContain('{{')

      // The sibling references inside project-bootstrap must resolve.
      expect(existsSync(join(root, 'modules', 'project-bootstrap', 'main.tf'))).toBe(true)
      expect(existsSync(join(root, 'modules', 'zitadel', 'main.tf'))).toBe(true)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('leaves the repository untouched', () => {
    const root = writeTemporaryRoot(REPO_ROOT)
    rmSync(root, { recursive: true, force: true })
    const module = join(REPO_ROOT, 'infrastructure', 'terraform', 'modules', 'project-bootstrap')
    expect(existsSync(join(module, '.terraform'))).toBe(false)
    expect(existsSync(join(module, '.terraform.lock.hcl'))).toBe(false)
  })
})
