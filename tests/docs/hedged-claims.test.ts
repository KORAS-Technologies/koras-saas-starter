import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { documents } from './documents.js'
import { join } from 'node:path'

/**
 * A hedged claim has to say when it was true.
 *
 * The fourth class in R-042, after paths, lists and identifiers. "does not
 * yet", "currently", "for now" -- sentences that are true when written and
 * decay silently, because nothing about the prose says whether the day it
 * describes is today. D1 said the generator-integration workflow "does not yet
 * build what it generates" for days after it did, and ranked itself the
 * highest-leverage work outstanding on the strength of it. IMPLEMENTATION_
 * ROADMAP said "a live apply is not currently reversible" for two days after
 * teardown was built.
 *
 * The rule is not "never hedge". A document that says what is undone is more
 * useful than one that does not, and FOLLOW_UPS is nothing but such claims.
 * The rule is that every hedge sits inside a dated context: the paragraph it
 * is in, or the nearest heading above it, or -- for a table -- its own row
 * carries an ISO date. A reader then knows the claim's age without asking,
 * and a stale one reads as stale rather than as current.
 *
 * Measured when written, 2026-09-15: 38 lines across the documents carried
 * one of the phrases, and a grep is what found them. Applying the rule left
 * 16 undated: four in SYNC_BACKLOG were dated or reworded in the same pass,
 * and the twelve in documents other passes held that day are exempt below,
 * each with a reason and most marked as pending one date. The rest sit in a
 * dated context already, because the documents that hedge most -- FOLLOW_UPS,
 * RISK_REGISTER, SYNC_BACKLOG -- date their entries by habit.
 */

const ROOT = join(__dirname, '..', '..')

/**
 * The phrases. Longer alternatives first, so "does not yet" is one match
 * rather than a "not yet" inside something else; the alternation is only
 * used to find lines, so the distinction changes nothing but the report.
 */
export const HEDGES = [
  'does not yet',
  'not yet',
  'not currently',
  'currently',
  'for now',
  'at the moment',
  'as of now',
  'still open',
  'until then',
  'to be created',
  'to be enabled',
] as const

const HEDGE = new RegExp(`\\b(${HEDGES.join('|')})\\b`, 'i')
const DATE = /\b20\d\d-\d\d-\d\d\b/

/**
 * Hedges that are legitimately undated, by file and by the text of the line.
 *
 * Two kinds for good. A risk *description* in a register table describes a
 * condition, not a moment -- "if the Control Plane is not yet deployed" is
 * true whenever it is true. And a quotation of old text inside its own
 * correction: the hedge is the finding, and dating it would say the
 * correction was made when the mistake was.
 *
 * And one kind for a day. "Pending edit 2026-09-15" marks a true claim in a
 * document another pass was editing when this test was written; each needs
 * one date added to its line and then leaves this list. Those entries are
 * the only ones that should ever read as a to-do.
 *
 * Each phrase must still occur on an undated hedge line of that file, and the
 * test below says so: an exemption that stops matching is a line nobody
 * deletes, and the next reader takes it as a description of the system.
 */
const EXEMPT: Record<string, Array<{ phrase: string; reason: string }>> = {
  'docs/RISK_REGISTER.md': [
    {
      phrase: 'If the Control Plane is not yet deployed',
      reason: 'R-001 description: a condition in a risk table, not a claim about today',
    },
    {
      phrase: 'if the Control Plane is not yet live',
      reason: 'R-001 mitigation: the same condition, in the same table',
    },
    // R-042's paragraph on this class, and R-036's list of what the first live
    // teardown left, were the seven entries here that read "pending edit
    // 2026-09-15". All seven were dated in the documents that afternoon and
    // left this list, which is the shape every temporary exemption should
    // take: a date, not a permanent excuse.
    {
      phrase: '**What is still open, and cannot be closed this way.**',
      reason: 'R-042 closing paragraph: the two classes nothing can reach, a standing condition',
    },
  ],
  'docs/BILLING_DESIGN.md': [
    {
      phrase: 'rendering two states it does not yet have',
      reason: 'the product-side summary; pending edit 2026-09-15',
    },
  ],
  'docs/PRODUCT_FRONTEND.md': [
    {
      phrase: 'will, and until then the cookie says the same thing.',
      reason: 'a sequence -- the cookie stands until the next request reads the store -- not a claim about today',
    },
    {
      phrase: "The web tier's API client does not yet send",
      reason: 'the language section, being written by another pass; pending edit 2026-09-15',
    },
  ],
  'docs/SYNC_BACKLOG.md': [
    {
      phrase: 'used to end "the workflow already exists; it does not yet',
      reason: 'a quotation of the old text inside its own correction',
    },
    {
      phrase: 'A stale "not yet" is the most expensive kind of wrong',
      reason: 'names the phrase as a phrase, in the paragraph explaining why it is dated',
    },
  ],
}


export interface Hedge {
  line: number
  text: string
  dated: boolean
}

/**
 * Every hedged line in a document, and whether its context is dated.
 *
 * The context is the paragraph -- the run of non-blank lines around it -- or
 * the nearest heading above. A table row is its own paragraph: a table is one
 * block of non-blank lines, and a date in one row says nothing about the claim
 * in another. Fenced code is skipped, because a quoted command output is not
 * a claim this repository makes.
 */
export function hedges(text: string): Hedge[] {
  const lines = text.split(/\r?\n/)
  const found: Hedge[] = []
  let fenced = false
  let heading = ''

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] as string
    if (/^\s*(```|~~~)/.test(line)) {
      fenced = !fenced
      continue
    }
    if (fenced) continue
    if (/^#{1,6}\s/.test(line)) heading = line
    if (!HEDGE.test(line)) continue

    const context = line.trim().startsWith('|') ? line : paragraphAround(lines, i)
    found.push({ line: i + 1, text: line, dated: DATE.test(context) || DATE.test(heading) })
  }
  return found
}

function paragraphAround(lines: string[], index: number): string {
  const blank = (line: string | undefined): boolean =>
    line === undefined || line.trim() === '' || /^\s*(```|~~~)/.test(line)
  let start = index
  while (!blank(lines[start - 1])) start--
  let end = index
  while (!blank(lines[end + 1])) end++
  return lines.slice(start, end + 1).join('\n')
}

function exempt(doc: string, hedge: Hedge): boolean {
  return (EXEMPT[doc] ?? []).some(({ phrase }) => hedge.text.includes(phrase))
}

/** `file:line: text`, so a failure is a place to go rather than a count. */
export function violations(doc: string, text: string): string[] {
  return hedges(text)
    .filter((hedge) => !hedge.dated && !exempt(doc, hedge))
    .map((hedge) => `${doc}:${String(hedge.line)}: ${hedge.text.trim()}`)
}

describe('hedged claims in the documentation', () => {
  const docs = documents()

  it('finds hedges to check', () => {
    // A phrase list matching nothing would make every case below pass
    // silently. The documents hedge; if this drops to zero, the regex broke.
    const total = docs.flatMap((doc) => hedges(readFileSync(join(ROOT, doc), 'utf8'))).length
    expect(total).toBeGreaterThan(10)
  })

  it.each(docs)('every hedge sits in a dated context, in %s', (doc) => {
    expect(
      violations(doc, readFileSync(join(ROOT, doc), 'utf8')),
      'These sentences hedge -- "not yet", "currently", "for now" -- with no ' +
        'date in their paragraph or their nearest heading. A hedge is true the ' +
        'day it is written and decays silently; date it, or exempt it here with a reason.',
    ).toEqual([])
  })

  it('exempts only hedges that are still there, and still undated', () => {
    for (const [doc, entries] of Object.entries(EXEMPT)) {
      const undated = hedges(readFileSync(join(ROOT, doc), 'utf8')).filter((hedge) => !hedge.dated)
      for (const { phrase, reason } of entries) {
        expect(
          undated.some((hedge) => hedge.text.includes(phrase)),
          `${doc} has no undated hedge containing "${phrase}" any more, so "${reason}" is stale`,
        ).toBe(true)
      }
    }
  })

  // Mutation checks: the rule applied to a document that exists only here.

  it('fails an undated hedge, and says where', () => {
    const doc = ['## Deployment', '', 'The worker does not yet run on a schedule.', ''].join('\n')
    expect(violations('temp.md', doc)).toEqual([
      'temp.md:3: The worker does not yet run on a schedule.',
    ])
  })

  it('accepts a hedge whose paragraph, heading or row is dated', () => {
    const inParagraph = ['## Deployment', '', 'As of 2026-09-15 the worker does not yet run.'].join('\n')
    const inHeading = ['## Deployment — 2026-09-15', '', 'The worker does not yet run.'].join('\n')
    const inRow = ['## Rows', '', '| a | b |', '|---|---|', '| 2026-09-15 | not yet run |'].join('\n')
    for (const doc of [inParagraph, inHeading, inRow]) expect(violations('temp.md', doc)).toEqual([])
  })

  it('does not let one dated row date the whole table', () => {
    const doc = ['## Rows', '', '| a | b |', '|---|---|', '| 2026-09-15 | done |', '| x | not yet |'].join('\n')
    expect(violations('temp.md', doc)).toHaveLength(1)
  })

  it('ignores fenced code, which quotes rather than claims', () => {
    const doc = ['## Output', '', '```', 'status: not yet provisioned', '```', ''].join('\n')
    expect(violations('temp.md', doc)).toEqual([])
  })
})
