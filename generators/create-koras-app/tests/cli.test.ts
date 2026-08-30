import { describe, it, expect } from 'vitest'
import { parseArgs } from '../src/cli/args.js'

describe('parseArgs', () => {
  it('parses project name as positional', () => {
    const args = parseArgs(['node', 'cli', 'myapp'])
    expect(args.project).toBe('myapp')
  })

  it('parses --profile', () => {
    const args = parseArgs(['node', 'cli', 'myapp', '--profile', 'product'])
    expect(args.profile).toBe('product')
  })

  it('parses --profile=value syntax', () => {
    const args = parseArgs(['node', 'cli', '--profile=control-plane'])
    expect(args.profile).toBe('control-plane')
  })

  it('parses --provision', () => {
    expect(parseArgs(['node', 'cli', '--provision']).provision).toBe(true)
  })

  it('parses --dry-run', () => {
    expect(parseArgs(['node', 'cli', '--dry-run']).dryRun).toBe(true)
  })

  it('parses --help', () => {
    expect(parseArgs(['node', 'cli', '--help']).help).toBe(true)
  })

  it('parses -h as --help', () => {
    expect(parseArgs(['node', 'cli', '-h']).help).toBe(true)
  })

  it('parses --list-profiles', () => {
    expect(parseArgs(['node', 'cli', '--list-profiles']).listProfiles).toBe(true)
  })

  it('parses --no-interactive', () => {
    expect(parseArgs(['node', 'cli', '--no-interactive']).noInteractive).toBe(true)
  })

  it('parses --output-dir', () => {
    const args = parseArgs(['node', 'cli', '--output-dir', '/tmp'])
    expect(args.outputDir).toBe('/tmp')
  })

  it('parses --with as a comma-separated list', () => {
    const args = parseArgs(['node', 'cli', '--with', 'marketing,ai_gateway'])
    expect(args.with).toEqual(['marketing', 'ai_gateway'])
  })

  it('parses --without and --without=value', () => {
    expect(parseArgs(['node', 'cli', '--without', 'worker']).without).toEqual(['worker'])
    expect(parseArgs(['node', 'cli', '--without=worker,admin']).without).toEqual([
      'worker',
      'admin',
    ])
  })

  it('accumulates repeated --with flags', () => {
    const args = parseArgs(['node', 'cli', '--with', 'marketing', '--with', 'ai_gateway'])
    expect(args.with).toEqual(['marketing', 'ai_gateway'])
  })

  it('defaults component overrides to empty lists', () => {
    const args = parseArgs(['node', 'cli'])
    expect(args.with).toEqual([])
    expect(args.without).toEqual([])
  })

  it('defaults provision to false', () => {
    expect(parseArgs(['node', 'cli']).provision).toBe(false)
  })

  it('defaults dryRun to false', () => {
    expect(parseArgs(['node', 'cli']).dryRun).toBe(false)
  })
})

describe('--push', () => {
  /**
   * The gap it closes: `--provision` pushes as its last step, `--provision-only`
   * deliberately does not, and there was no third option -- so generating and
   * provisioning as two steps left a full estate, a repository holding one
   * auto-init commit, and no supported way to connect them.
   */
  it('operates on an existing project without provisioning anything', () => {
    const args = parseArgs(['node', 'cli', 'app', '--profile', 'product', '--push'])
    expect(args.push).toBe(true)
    expect(args.provision).toBe(false)
    expect(args.provisionOnly).toBe(false)
  })

  it('does not imply registration, which is a different operation', () => {
    expect(parseArgs(['node', 'cli', 'app', '--profile', 'product', '--push']).registerOnly).toBe(
      false,
    )
  })

  it('is off unless asked for', () => {
    expect(parseArgs(['node', 'cli', 'app', '--profile', 'product']).push).toBe(false)
  })
})

describe('--register-only', () => {
  /**
   * The whole point of the flag. `--provision-only` implies `--provision`
   * because there is nothing else it could mean; this one must not, because
   * re-sending a reference and rebuilding an estate are different operations
   * and only one of them is safe to run casually against production.
   */
  it('never implies provisioning', () => {
    const args = parseArgs(['node', 'cli', 'app', '--profile', 'product', '--register-only'])
    expect(args.registerOnly).toBe(true)
    expect(args.provision).toBe(false)
    expect(args.provisionOnly).toBe(false)
  })

  it('accepts a Control Plane override, for re-registering against a different registry', () => {
    const args = parseArgs([
      'node', 'cli', 'app', '--profile', 'product', '--register-only',
      '--control-plane-url', 'https://cp.example',
    ])
    expect(args.registerOnly).toBe(true)
    expect(args.controlPlaneUrl).toBe('https://cp.example')
  })

  it('is off unless asked for', () => {
    expect(parseArgs(['node', 'cli', 'app', '--profile', 'product']).registerOnly).toBe(false)
  })
})

describe('--refresh-modules', () => {
  it('operates on an existing project without implying provisioning', () => {
    const args = parseArgs(['node', 'cli', 'app', '--profile', 'product', '--refresh-modules'])
    expect(args.refreshModules).toBe(true)
    // Refreshing source files must never quietly become an infrastructure run.
    expect(args.provision).toBe(false)
    expect(args.provisionOnly).toBe(false)
  })

  it('combines with --provision-only', () => {
    const args = parseArgs([
      'node', 'cli', 'app', '--profile', 'product', '--refresh-modules', '--provision-only',
    ])
    expect(args.refreshModules).toBe(true)
    expect(args.provisionOnly).toBe(true)
    expect(args.provision).toBe(true)
  })

  it('is off unless asked for', () => {
    expect(parseArgs(['node', 'cli', 'app', '--profile', 'product']).refreshModules).toBe(false)
  })
})
