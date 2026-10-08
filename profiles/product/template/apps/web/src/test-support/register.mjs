import { register } from 'node:module'

/**
 * `node --import ./src/test-support/register.mjs --test ...`: installs the
 * TypeScript/JSX hooks before any test file is evaluated, and tells React
 * that updates in these tests are wrapped in `act()`.
 */
register('./tsx-loader.mjs', import.meta.url)
globalThis.IS_REACT_ACT_ENVIRONMENT = true
