#!/usr/bin/env node
/**
 * Combine a generated Postman collection with a hand-maintained "custom"
 * fragment (CI Smoke, Security & Negative Tests) into the final collection a
 * repository commits.
 *
 * The two halves never overwrite each other on regeneration: `generate.mjs`
 * always rebuilds the generated half from the live OpenAPI schema and always
 * re-reads the custom fragment from `tooling/postman/templates/`, so editing
 * a security test means editing the template, not the generated output.
 * Every folder from the custom fragment is tagged with a `koras.custom`
 * marker in its description so a human opening the file (or a future merge)
 * can tell the two apart at a glance.
 *
 * Usage:
 *   node merge-custom.mjs --generated <file> --custom <file> --out <file>
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { dirname } from 'node:path'

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

function markCustom(folder) {
  const marker = '[koras.custom: hand-maintained -- edit the template in tooling/postman/templates/, not this file]'
  return {
    ...folder,
    description: folder.description ? `${folder.description}\n\n${marker}` : marker,
  }
}

function main() {
  const args = parseArgs(process.argv.slice(2))
  if (!args.generated || !args.out) {
    console.error('Usage: node merge-custom.mjs --generated <file> --custom <file> --out <file>')
    process.exit(1)
  }

  const generated = JSON.parse(readFileSync(args.generated, 'utf-8'))
  const customFolders =
    args.custom && existsSync(args.custom) ? JSON.parse(readFileSync(args.custom, 'utf-8')).item ?? [] : []

  const smoke = customFolders.filter((f) => f.name === 'CI Smoke').map(markCustom)
  const security = customFolders.filter((f) => f.name === 'Security & Negative Tests').map(markCustom)
  const rest = customFolders
    .filter((f) => f.name !== 'CI Smoke' && f.name !== 'Security & Negative Tests')
    .map(markCustom)

  const merged = {
    ...generated,
    item: [...smoke, ...generated.item, ...rest, ...security],
  }

  mkdirSync(dirname(args.out), { recursive: true })
  writeFileSync(args.out, JSON.stringify(merged, null, 2))
  console.log(
    `wrote ${args.out}: ${generated.item.length} generated folders + ${customFolders.length} custom folders`,
  )
}

main()
