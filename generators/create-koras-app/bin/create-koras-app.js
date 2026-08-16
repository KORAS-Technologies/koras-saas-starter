#!/usr/bin/env node
// Thin shim that delegates to the compiled CLI in dist/.
let run
try {
  ;({ run } = await import('../dist/cli/index.js'))
} catch (err) {
  if (err?.code === 'ERR_MODULE_NOT_FOUND') {
    console.error(
      'create-koras-app is not built.\n' +
        '  Run: pnpm --filter create-koras-app build',
    )
    process.exit(1)
  }
  throw err
}

run(process.argv).catch((err) => {
  console.error(err instanceof Error ? err.message : String(err))
  process.exit(1)
})
