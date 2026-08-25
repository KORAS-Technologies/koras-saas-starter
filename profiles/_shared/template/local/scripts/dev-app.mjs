// Starts a Next.js dev server on the port resolved for it in local/.env.
//
// The port cannot live in package.json: it is a host-global resource, and a
// literal there collides with any other project — including a second KORAS
// stack — the moment two run at once. `local/scripts/ports.sh` resolves an
// available port per machine; this reads that answer.
//
// Node rather than a shell one-liner because `${VAR:-default}` is POSIX syntax
// that cmd.exe does not expand, and package.json scripts run under whatever
// shell the platform provides.
import { spawn } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const [variable, fallback] = process.argv.slice(2)

if (!variable) {
  console.error('usage: dev-app.mjs <PORT_VARIABLE> [fallback]')
  process.exit(1)
}

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const envFile = join(projectRoot, 'local', '.env')

function resolvePort() {
  if (process.env[variable]) return process.env[variable]

  if (existsSync(envFile)) {
    for (const line of readFileSync(envFile, 'utf8').split('\n')) {
      const match = /^([A-Z0-9_]+)=(\d+)\s*$/.exec(line.trim())
      if (match && match[1] === variable) return match[2]
    }
  }

  // No resolution yet — `make bootstrap` has not run. The preference still
  // starts a usable server on a machine where nothing else wants the port.
  return fallback
}

const port = resolvePort()

if (!port) {
  console.error(
    `No port for ${variable}. Run \`make bootstrap\` (or \`make ports\`) to resolve one.`,
  )
  process.exit(1)
}

// Resolve Next's own entry rather than the .bin shim: on Windows that shim is a
// .cmd file, which Node refuses to spawn without a shell.
//
// Resolution is anchored to the app package, not to this file. pnpm does not
// hoist, so `next` exists under apps/<name>/node_modules and is invisible from
// local/scripts/. The app directory is the cwd because that is where the
// package's own `dev` script runs.
const nextBin = createRequire(join(process.cwd(), 'package.json')).resolve('next/dist/bin/next')

const child = spawn(process.execPath, [nextBin, 'dev', '--port', port], {
  stdio: 'inherit',
  shell: false,
})

// Forward the signals a dev server is expected to honour, so Ctrl-C still stops
// Next rather than orphaning it behind this wrapper.
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => child.kill(signal))
}

child.on('exit', (code, signal) => {
  process.exit(signal ? 1 : (code ?? 1))
})
