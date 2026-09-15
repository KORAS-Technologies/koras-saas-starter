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
     * nothing: a test that genuinely hangs still fails, two minutes later
     * instead of five seconds later, and the alternative -- a per-file override
     * in nine files -- is nine places to forget.
     *
     * Two minutes rather than one, because one was measured and was not
     * enough. A drift test that generates a project runs in 4 to 18 seconds on
     * an idle machine and crossed 60 seconds twice while the rest of this
     * suite, another repository's suite and a full product build shared the
     * disk. A budget that only holds when nothing else is running is a budget
     * that fails in CI on a bad afternoon and passes on re-run, which is worse
     * than no budget: it teaches everyone to re-run.
     */
    testTimeout: 120_000,
    hookTimeout: 120_000,
  },
})
