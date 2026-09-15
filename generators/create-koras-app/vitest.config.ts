import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['tests/**/*.test.ts'],
    /**
     * A minute, because these tests start real processes.
     *
     * Nine files here spawn `bash`, `git`, a stubbed `doppler` or a whole
     * generation, and `registration-lifecycle.test.ts` says in a comment that
     * the script it runs takes tens of seconds. vitest's default is five,
     * which they met under vitest 2 by luck of scheduling and stopped meeting
     * under vitest 4, which runs more files at once (R-031). Raising it weakens
     * nothing: a test that genuinely hangs still fails, a minute later instead
     * of five seconds later, and the alternative -- a per-file override in nine
     * files -- is nine places to forget.
     */
    testTimeout: 60_000,
    hookTimeout: 60_000,
  },
})
