// Stop a child and everything it started.
//
// `child.kill()` signals the direct child and nothing below it, and every dev
// command here has something below it:
//
//   dev-service  spawns `uv`, which spawns Python. On Windows it also goes
//                through cmd.exe, because `shell: true` is needed to find uv.
//   dev-app      spawns Node running Next, which forks its own workers.
//
// So stopping the wrapper stops the wrapper. The grandchild keeps the port and
// the file handles, and the next thing that needs either fails with a message
// about neither: one session ended with an orphaned worker holding port 8000
// and an open handle on the API executable, which blocked removing the whole
// worktree, long after the process that appeared to own it had gone.
//
// Terminating the GROUP is the fix, and it is two different mechanisms:
//
//   POSIX    The child is spawned detached, so it leads its own process
//            group, and a negative pid signals the group.
//   Windows  There are no process groups in that sense. `taskkill /T` walks
//            the tree by parent pid, and /F is required because a console
//            application that is not pumping messages will not answer
//            anything gentler.
import { spawnSync } from 'node:child_process'

/** POSIX only. Detaching makes the child a group leader so the group is killable. */
export const groupSpawnOptions = process.platform === 'win32' ? {} : { detached: true }

/**
 * Terminate `child` and every process it started.
 *
 * Returns nothing and throws nothing: this runs while something is already
 * shutting down, and a failure to reap a process that has already exited is
 * not worth an error on the way out.
 */
export function killTree(child, signal = 'SIGTERM') {
  if (!child || child.exitCode !== null || child.pid === undefined) return

  if (process.platform === 'win32') {
    // /T the tree, /F because a console app mid-shutdown will not answer a
    // polite request. stdio ignored: taskkill reporting "process not found"
    // for something that just exited is noise on the way out.
    spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
    return
  }

  try {
    // Negative pid: the group, not just the leader.
    process.kill(-child.pid, signal)
  } catch {
    // The group is gone already, or the child was never detached. Fall back
    // to the child alone rather than leaving it running.
    try {
      child.kill(signal)
    } catch {
      /* already gone */
    }
  }
}

/** Forward the signals a dev server is expected to honour, to the whole tree. */
export function forwardSignals(child) {
  for (const signal of ['SIGINT', 'SIGTERM']) {
    process.on(signal, () => killTree(child, signal))
  }
  // Also on our own exit, so a crash in the wrapper does not leave the tree
  // running. This is the path that produced the orphan: the wrapper died and
  // nothing had told anything below it to stop.
  process.on('exit', () => killTree(child, 'SIGTERM'))
}
