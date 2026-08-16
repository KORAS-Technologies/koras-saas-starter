import { existsSync } from 'node:fs'
import { join } from 'node:path'

export interface ConflictResult {
  conflict: boolean
  message?: string
}

export function checkDirectoryConflict(outputDir: string, slug: string): ConflictResult {
  const targetPath = join(outputDir, slug)
  if (existsSync(targetPath)) {
    return {
      conflict: true,
      message: [
        `Directory already exists: ${targetPath}`,
        '  Remove the directory or choose a different project name.',
      ].join('\n'),
    }
  }
  return { conflict: false }
}
