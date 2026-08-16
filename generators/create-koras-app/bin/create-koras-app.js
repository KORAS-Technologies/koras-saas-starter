#!/usr/bin/env node
// Thin shim that delegates to the compiled TypeScript source via tsx (dev)
// or to the built dist/ in production.
import { run } from '../src/cli/index.js'
run(process.argv).catch((err) => {
  console.error(err instanceof Error ? err.message : String(err))
  process.exit(1)
})
