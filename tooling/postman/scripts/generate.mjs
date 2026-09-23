#!/usr/bin/env node
/**
 * The one command a repository runs to (re)generate its Postman collection
 * and DEV environment from its own, real, currently implemented API.
 *
 * Pipeline: extract_openapi.py (imports the real FastAPI app and calls its
 * own .openapi()) -> openapi-to-postman.mjs (schema -> generated collection)
 * -> merge-custom.mjs (splice in the hand-maintained CI Smoke and Security &
 * Negative Tests folders for this profile) -> generate-environment.mjs
 * (scan the final collection for every {{variable}} it references).
 *
 * Usage (from a generated product or koras-control-plane):
 *   node tooling/postman/scripts/generate.mjs --profile product --name Docoris
 *   node tooling/postman/scripts/generate.mjs --profile control-plane --name "Koras Control Plane"
 *
 * `--profile` selects the custom fragment (control-plane-custom / product-custom)
 * and the base-url variable (control_plane_base_url / product_base_url).
 * Everything else is derived from the repository this is run in: the service
 * directory is always services/api, the output is always postman/ at the
 * repository root.
 */
import { spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const TOOLING_ROOT = resolve(SCRIPT_DIR, '..')

const PROFILE_DEFAULTS = {
  'control-plane': { baseUrlVar: 'control_plane_base_url', baseUrl: 'http://localhost:8000', correlationHeader: 'X-Request-Id', slug: 'Koras-Control-Plane' },
  product: { baseUrlVar: 'product_base_url', baseUrl: 'http://localhost:8001', correlationHeader: undefined, slug: undefined },
}

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

function run(cmd, args) {
  console.log(`\n$ ${cmd} ${args.join(' ')}`)
  const result = spawnSync(cmd, args, { stdio: 'inherit' })
  if (result.status !== 0) {
    throw new Error(`${cmd} exited with status ${result.status}`)
  }
}

function main() {
  const args = parseArgs(process.argv.slice(2))
  const profile = args.profile
  if (!profile || !PROFILE_DEFAULTS[profile]) {
    console.error('Usage: node generate.mjs --profile <control-plane|product> --name "<Display Name>" [--repo-root .] [--python python]')
    process.exit(1)
  }
  const defaults = PROFILE_DEFAULTS[profile]
  const repoRoot = resolve(args['repo-root'] ?? process.cwd())
  const name = args.name ?? (profile === 'control-plane' ? 'Koras Control Plane' : 'Koras Product')
  const slug = args.slug ?? defaults.slug ?? name.replace(/\s+/g, '-')
  // Resolve which Python to run the extractor with. Preference order:
  // 1. `--python`, explicit.
  // 2. The repo's own `.venv` interpreter, called directly by path. This is
  //    the reliable option: `uv run --no-project` was tried first and
  //    dropped -- "avoid discovering the project" (uv's own description of
  //    the flag) turned out to also mean "sometimes skip discovering the
  //    already-built .venv sitting right there", reproducibly in one shell
  //    and not another on the same machine, which is a worse failure mode
  //    than depending on anything (a ModuleNotFoundError for fastapi, from a
  //    script that never touches fastapi's behavior, only its route table).
  //    A direct path has no discovery step to get wrong.
  // 3. `uv run --no-project python`, if there is a uv.lock but no .venv yet
  //    (nothing has been synced) -- best-effort, since there is nothing to
  //    point at directly.
  // 4. Plain `python` on PATH.
  const venvPython = process.platform === 'win32'
    ? join(repoRoot, '.venv', 'Scripts', 'python.exe')
    : join(repoRoot, '.venv', 'bin', 'python')
  const python = args.python
    ?? (existsSync(venvPython) ? venvPython : null)
    ?? (existsSync(join(repoRoot, 'uv.lock')) ? 'uv run --no-project python' : 'python')

  const serviceDir = join(repoRoot, 'services', 'api')
  if (!existsSync(join(serviceDir, 'koras_api', 'main.py'))) {
    throw new Error(`${serviceDir} does not look like a KORAS API service directory (no koras_api/main.py)`)
  }

  const workDir = mkdtempSync(join(tmpdir(), 'koras-postman-'))
  try {
    const openapiPath = join(workDir, 'openapi.json')
    const generatedPath = join(workDir, 'generated.postman_collection.json')
    const finalCollectionPath = join(repoRoot, 'postman', `${slug}-DEV.postman_collection.json`)
    const environmentPath = join(repoRoot, 'postman', 'environments', 'DEV.postman_environment.json')
    const customFragment = join(TOOLING_ROOT, 'templates', `${profile}-custom.postman_collection.json`)

    // `python` is either a single executable path (the resolved .venv
    // interpreter, or plain `python`) or the multi-word `uv run --no-project
    // python` fallback -- split into argv only in the latter case, so a
    // space in a repository's own path is never mistaken for an argument
    // separator.
    const [pythonCmd, ...pythonPrefixArgs] = python.startsWith('uv run') ? python.split(' ') : [python]
    run(pythonCmd, [...pythonPrefixArgs, join(SCRIPT_DIR, 'extract_openapi.py'), '--service-dir', serviceDir, '--out', openapiPath])

    const converterArgs = [
      join(SCRIPT_DIR, 'openapi-to-postman.mjs'),
      '--openapi', openapiPath,
      '--out', generatedPath,
      '--name', name,
      '--base-url-var', defaults.baseUrlVar,
      '--source-label', `${slug} services/api`,
    ]
    if (defaults.correlationHeader) converterArgs.push('--correlation-header', defaults.correlationHeader)
    run('node', converterArgs)

    run('node', [
      join(SCRIPT_DIR, 'merge-custom.mjs'),
      '--generated', generatedPath,
      '--custom', customFragment,
      '--out', finalCollectionPath,
    ])

    run('node', [
      join(SCRIPT_DIR, 'generate-environment.mjs'),
      '--collection', finalCollectionPath,
      '--out', environmentPath,
      '--name', `${name} - DEV`,
      '--base-url-var', defaults.baseUrlVar,
      '--base-url', defaults.baseUrl,
    ])

    console.log(`\nDone. Collection: ${finalCollectionPath}\nEnvironment: ${environmentPath}`)
  } finally {
    rmSync(workDir, { recursive: true, force: true })
  }
}

main()
