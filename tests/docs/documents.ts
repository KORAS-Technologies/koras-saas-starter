import { readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const ROOT = join(__dirname, '..', '..')

/**
 * Every Markdown document R-042's mechanical checks read.
 *
 * **One walk, because three drifted.** `file-references`, `identifiers` and
 * `hedged-claims` each carried their own copy of this function. Two of them
 * listed `docs/` without recursing and one of them walked the tree, so the
 * hedge check covered 98 documents while the path and identifier checks
 * covered 36 -- and the 62 under `docs/adr/`, `docs/features/` and
 * `docs/platform/` were unchecked for invented paths and invented identifiers
 * for as long as those directories had existed. That is PLAT-DEF-004.
 *
 * The defect was not that a walk was wrong. It was that there were three of
 * them and fixing one fixed one, which is why this is a module rather than a
 * corrected copy pasted into two more files: a fourth check added tomorrow
 * imports this and is right by construction, and the next person to improve
 * the traversal improves it everywhere at once.
 *
 * `CLAUDE.md` is included because it sits at the repository root by design --
 * only it and `README.md` do -- and it is the file every session reads first,
 * which has twice made it the place a decayed claim did the most damage.
 */
export function documents(): string[] {
  const found: string[] = []
  const walk = (dir: string): void => {
    for (const name of readdirSync(join(ROOT, dir)).sort()) {
      const relative = `${dir}/${name}`
      if (statSync(join(ROOT, relative)).isDirectory()) walk(relative)
      else if (name.endsWith('.md')) found.push(relative)
    }
  }
  walk('docs')
  return [...found, 'CLAUDE.md']
}
