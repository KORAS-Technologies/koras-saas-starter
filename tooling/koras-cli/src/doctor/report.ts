import { redact } from './redact.js'
import type { DoctorResult } from './types.js'

/**
 * Output formatting.
 *
 * The normal output is a list of rows and one verdict — nothing else. No
 * counts, no matrix, no timing, no per-check success detail. The value of this
 * command is that a passing run is boring and a failing run is obvious, and
 * both are readable at a glance.
 */

export const PASS = '✓'
export const FAIL = '✗'

export const READY = 'READY FOR BOOTSTRAP'
export const NOT_READY = 'NOT READY FOR BOOTSTRAP'

export interface ReportRow {
  label: string
  result: DoctorResult
}

/** Widest label plus padding, so the marks line up in a column. */
function labelWidth(rows: ReportRow[]): number {
  return Math.max(...rows.map((r) => r.label.length)) + 2
}

export function formatReport(rows: ReportRow[], env: NodeJS.ProcessEnv = process.env): string {
  const width = labelWidth(rows)
  const lines: string[] = ['Koras Bootstrap Doctor', '']

  for (const row of rows) {
    lines.push(`${row.label.padEnd(width)}${row.result.passed ? PASS : FAIL}`)
  }

  const failures = rows.filter((row) => !row.result.passed)

  // Only failures get detail. Every string is redacted on the way out —
  // provider errors are the most likely place for a credential to surface.
  if (failures.length > 0) {
    const withDetail = failures.filter((row) => row.result.error)
    if (withDetail.length > 0) {
      lines.push('', 'Failures:')
      for (const row of withDetail) {
        lines.push('', row.label, redact(row.result.error as string, env))
      }
    }
  }

  lines.push('', failures.length === 0 ? READY : NOT_READY)
  return lines.join('\n')
}

export function exitCode(rows: ReportRow[]): 0 | 1 {
  return rows.every((row) => row.result.passed) ? 0 : 1
}
