import { readFile } from 'node:fs/promises'
import { URL, fileURLToPath } from 'node:url'
import ts from 'typescript'

/**
 * Module hooks that let `node --test` import the real `.ts` / `.tsx` sources
 * of `apps/web` and the workspace packages, so a component test renders the
 * component that ships rather than a copy of it.
 *
 * Two jobs. `resolve` completes the extensionless imports the bundler
 * normally completes (`./ImportPanel` -> `./ImportPanel.tsx`, `next/link` ->
 * `next/link.js`) and swaps the import panel's server actions (`'use server'`,
 * wired to the API client and `next/cache`) for the stub in
 * `imports-actions.stub.mjs`, which a test drives. `load` transpiles
 * TypeScript and JSX with the workspace's own `typescript`, types erased, no
 * type check: `pnpm typecheck` owns that.
 *
 * Plain JavaScript because CI runs Node 20, which cannot strip types; the
 * hooks API (`module.register`) exists from Node 20.6.
 */

const EXTENSIONS = ['.ts', '.tsx', '.js', '/index.ts', '/index.tsx', '/index.js']
const IMPORTS_ACTIONS = /\/app\/dashboard\/imports\/actions(\.ts)?$/
const IMPORTS_STUB = new URL('./imports-actions.stub.mjs', import.meta.url).href

const COMPILER_OPTIONS = {
  module: ts.ModuleKind.ESNext,
  target: ts.ScriptTarget.ES2022,
  jsx: ts.JsxEmit.ReactJSX,
  esModuleInterop: true,
}

function isRelative(specifier) {
  return specifier.startsWith('./') || specifier.startsWith('../') || specifier.startsWith('/')
}

export async function resolve(specifier, context, nextResolve) {
  if (context.parentURL !== undefined && isRelative(specifier)) {
    const target = new URL(specifier, context.parentURL)
    // Next.js dynamic-segment folders (`[key]`) percent-encode their brackets
    // in a file:// URL's pathname; decode before matching.
    const pathname = decodeURIComponent(target.pathname)
    if (IMPORTS_ACTIONS.test(pathname)) {
      return { url: IMPORTS_STUB, format: 'module', shortCircuit: true }
    }
  }
  try {
    return await nextResolve(specifier, context)
  } catch (error) {
    const code = error?.code
    if (code !== 'ERR_MODULE_NOT_FOUND' && code !== 'ERR_UNSUPPORTED_DIR_IMPORT') {
      throw error
    }
    for (const extension of EXTENSIONS) {
      try {
        return await nextResolve(specifier + extension, context)
      } catch {
        // try the next one
      }
    }
    throw error
  }
}

export async function load(url, context, nextLoad) {
  if (!url.startsWith('file:') || !/\.tsx?$/.test(url)) {
    return nextLoad(url, context)
  }
  const fileName = fileURLToPath(url)
  const source = await readFile(fileName, 'utf8')
  const { outputText } = ts.transpileModule(source, { compilerOptions: COMPILER_OPTIONS, fileName })
  return { format: 'module', source: outputText, shortCircuit: true }
}
