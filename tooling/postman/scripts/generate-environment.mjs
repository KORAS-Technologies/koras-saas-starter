#!/usr/bin/env node
/**
 * Build a Postman DEV environment file from a generated collection: scan it
 * for every `{{variable}}` reference and emit one entry per name, plus a
 * fixed set of identity variables every KORAS environment needs regardless
 * of whether the current collection happens to reference them yet (so
 * switching between the Control Plane and a product environment in the same
 * workspace does not require re-adding `access_token` by hand).
 *
 * Secret-shaped variables (token, secret, key, password) are written with an
 * empty value and Postman's "secret" type, which Postman masks in the UI and
 * excludes from `postman collection export` unless the exporter opts in.
 * Nothing here ever carries a real credential -- that is the whole point of
 * an environment file that gets committed.
 */

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { dirname } from 'node:path'

const ALWAYS_PRESENT = {
  control_plane_base_url: 'http://localhost:8000',
  product_base_url: 'http://localhost:8001',
  api_version: 'v1',
  access_token: '',
  organization_id: '',
  tenant_id: '',
  tenant_slug: '',
  product_id: '',
  product_key: '',
  user_id: '',
}

const SECRET_PATTERN = /token|secret|key|password|credential/i

function parseArgs(argv) {
  const out = {}
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i].startsWith('--')) {
      out[argv[i].slice(2)] = argv[i + 1]
      i += 1
    }
  }
  return out
}

function extractVariables(collection) {
  const found = new Set()
  const pattern = /\{\{([a-zA-Z0-9_]+)\}\}/g
  const text = JSON.stringify(collection)
  let match
  while ((match = pattern.exec(text)) !== null) {
    found.add(match[1])
  }
  return found
}

function main() {
  const args = parseArgs(process.argv.slice(2))
  if (!args.collection || !args.out || !args.name) {
    console.error('Usage: node generate-environment.mjs --collection <file> --out <file> --name <name> [--base-url-var VAR --base-url VALUE]')
    process.exit(1)
  }

  const collection = JSON.parse(readFileSync(args.collection, 'utf-8'))
  const names = extractVariables(collection)
  for (const key of Object.keys(ALWAYS_PRESENT)) names.add(key)

  if (args['base-url-var']) {
    ALWAYS_PRESENT[args['base-url-var']] = args['base-url'] ?? ALWAYS_PRESENT[args['base-url-var']] ?? ''
    names.add(args['base-url-var'])
  }

  const values = [...names]
    .sort()
    .map((key) => ({
      key,
      value: ALWAYS_PRESENT[key] ?? '',
      type: SECRET_PATTERN.test(key) ? 'secret' : 'default',
      enabled: true,
    }))

  const environment = {
    id: undefined,
    name: args.name,
    values,
    _postman_variable_scope: 'environment',
  }

  mkdirSync(dirname(args.out), { recursive: true })
  writeFileSync(args.out, JSON.stringify(environment, null, 2))
  console.log(`wrote ${args.out}: ${values.length} variables (${values.filter((v) => v.type === 'secret').length} secret)`)
}

main()
