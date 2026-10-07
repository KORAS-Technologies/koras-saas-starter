#!/usr/bin/env node
// CI guard: docs/framework-baseline.yaml must name a commit that resolves and
// is an ancestor of, or equal to, HEAD. Needs full history (fetch-depth: 0).
// Plain node, no install: it reads one line and asks git.
import { readFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'

const file = 'docs/framework-baseline.yaml'
const match = /^accepted_baseline:\s*([0-9a-f]{7,40})\s*$/im.exec(readFileSync(file, 'utf8'))
if (!match) {
  console.error(`${file}: accepted_baseline must be a commit SHA`)
  process.exit(1)
}
const sha = match[1]
const git = (...args) => spawnSync('git', args, { encoding: 'utf8' })

if (git('rev-parse', '--verify', '--quiet', `${sha}^{commit}`).status !== 0) {
  console.error(`accepted_baseline ${sha} does not resolve (shallow checkout, or not a commit of this repository)`)
  process.exit(1)
}
if (git('merge-base', '--is-ancestor', sha, 'HEAD').status !== 0) {
  console.error(`accepted_baseline ${sha} is not an ancestor of HEAD`)
  process.exit(1)
}
console.log(`accepted_baseline ${sha} resolves and is an ancestor of HEAD`)
