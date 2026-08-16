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

  it('defaults provision to false', () => {
    expect(parseArgs(['node', 'cli']).provision).toBe(false)
  })

  it('defaults dryRun to false', () => {
    expect(parseArgs(['node', 'cli']).dryRun).toBe(false)
  })
})
