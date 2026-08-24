// Starts one Python service for local development.
//
// The sibling of dev-app.mjs, for the same reason: host ports are resolved per
// machine by local/scripts/ports.sh, so they cannot be literals in package.json.
// This also loads .env.local into the child environment. The services read
// their configuration from the process environment (pydantic-settings), and
// without this they would look for a .env inside services/<name>/, which is not
// where the repository keeps it.
import { spawn } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const [service] = process.argv.slice(2)

const COMMANDS = {
  // --reload watches src/ so edits restart the server, matching Next dev.
  api: (port) => ['uvicorn', 'koras_api.main:app', '--host', '127.0.0.1', '--port', port, '--reload'],
  worker: () => ['arq', 'koras_worker.worker.WorkerSettings'],
  scheduler: () => ['python', '-m', 'koras_scheduler.main'],
  // Only present in the product profile; harmless here.
  'ai-gateway': (port) => ['uvicorn', 'koras_ai_gateway.main:app', '--host', '127.0.0.1', '--port', port, '--reload'],
}

// Only the API publishes a port; the worker and scheduler are queue consumers.
const PORT_VARIABLE = { api: 'KORAS_PORT_SERVICE_API', 'ai-gateway': 'KORAS_PORT_SERVICE_AI_GATEWAY' }
const PORT_FALLBACK = { api: '8000', 'ai-gateway': '4000' }

if (!service || !(service in COMMANDS)) {
  console.error(`usage: dev-service.mjs <${Object.keys(COMMANDS).join('|')}>`)
  process.exit(1)
}

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..')

function parseEnvFile(file) {
  const values = {}
  if (!existsSync(file)) return values
  for (const line of readFileSync(file, 'utf8').split('\n')) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const index = trimmed.indexOf('=')
    if (index === -1) continue
    values[trimmed.slice(0, index)] = trimmed.slice(index + 1)
  }
  return values
}

const portsEnv = parseEnvFile(join(projectRoot, 'local', '.env'))
const localEnv = parseEnvFile(join(projectRoot, '.env.local'))

if (!existsSync(join(projectRoot, '.env.local'))) {
  console.error('No .env.local found. Run `make bootstrap` first.')
  process.exit(1)
}

const variable = PORT_VARIABLE[service]
const port = variable
  ? process.env[variable] ?? portsEnv[variable] ?? PORT_FALLBACK[service]
  : undefined

if (variable && !port) {
  console.error(`No port for ${variable}. Run \`make bootstrap\` (or \`make ports\`).`)
  process.exit(1)
}

// Precedence: the real environment wins over .env.local, which wins over the
// resolved ports. That lets a developer override any single value inline
// without editing files.
const env = { ...portsEnv, ...localEnv, ...process.env }

const child = spawn('uv', ['run', ...COMMANDS[service](port)], {
  cwd: join(projectRoot, 'services', service),
  stdio: 'inherit',
  shell: process.platform === 'win32',
  env,
})

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => child.kill(signal))
}

child.on('exit', (code, signal) => {
  process.exit(signal ? 1 : (code ?? 1))
})
