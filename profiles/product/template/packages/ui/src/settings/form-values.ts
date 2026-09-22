/**
 * Reading a submitted settings form back into values, and deciding what
 * counts as "held here".
 *
 * **Why this is a package file and not part of the application's own
 * `lib/setting-fields.ts`.** That file is a Handlebars template importing
 * `@<project>/api-client`, so nothing in this repository can execute it — and
 * what lives here is exactly the part with a right and a wrong answer. An
 * independent review of the SET-05 and SET-06 corrections made the point in
 * one sentence: change `same()` to `return true` and no setting can be saved
 * on either page, while every assertion about those corrections still passes,
 * because all of them were substring searches over template text.
 *
 * So the deciding logic is here, in plain TypeScript with no project-slug
 * import, where `product-settings-logic.test.ts` runs it against real
 * `FormData`. The application file keeps the parts that genuinely need the
 * generated types and does no deciding of its own.
 */

/** The little a form parser needs to know about a definition. */
export interface FormDefinition {
  key: string
  category: string
  data_type: string
}

/** The name prefix of the hidden input carrying what a field was rendered with. */
export const BASELINE_PREFIX = '__baseline.'

/**
 * What "this scope has chosen a value" means on a page.
 *
 * At member scope it is `a-row-exists`, and that is exactly right: a member
 * row is written only when a person chooses one, so its presence *is* the
 * choice. Comparing there would be wrong for anybody who deliberately picks
 * the value their organisation already has.
 *
 * At organisation scope a row exists for **every** organisation-scoped key
 * from the moment the tenant is provisioned, because the snapshot copies the
 * whole catalogue in. `a-row-exists` is then true of everything, every field
 * reads as modified, none ever reads as inherited, and the marker carries no
 * information at all.
 */
export type HeldMeans = 'a-row-exists' | 'differs-from-inherited'

/**
 * Two values the same, for the purpose of deciding whether somebody changed one.
 *
 * `JSON.stringify` rather than `===` because a `string_list` is an array and
 * two arrays with the same entries are never `===`.
 *
 * **It has two callers and they differ.** From `valuesForCategory` both
 * operands came through `parseSubmitted`, so an object's keys are in the order
 * the sender wrote them and a spurious inequality costs one redundant write.
 * From `isHeldHere` they are decoded from the API's JSON, where two
 * independently serialised `jsonb` objects may order their keys differently —
 * there a spurious inequality costs a wrong "changed here" marker and a Reset
 * button on a field nobody touched. No shipped setting is object-valued, so
 * neither is reachable today; the asymmetry is written down because the first
 * version of this comment claimed the cheap consequence for both.
 */
export function same(left: unknown, right: unknown): boolean {
  return JSON.stringify(left ?? null) === JSON.stringify(right ?? null)
}

/**
 * Whether this scope has chosen a value for a field, under one page's rule.
 *
 * `hasRow` is the presence of a key in what this scope stores; `value` is what
 * it stores; `fallback` is what would apply without it.
 */
export function isHeldHere(
  hasRow: boolean,
  value: unknown,
  fallback: unknown,
  heldMeans: HeldMeans,
): boolean {
  return heldMeans === 'a-row-exists' ? hasRow : hasRow && !same(value, fallback)
}

/**
 * One submitted or baseline value, typed the way the definition says.
 *
 * `undefined` means "nothing usable arrived", and a caller writes nothing for
 * it. A boolean is decided by presence, which is the whole reason the caller
 * walks the definitions rather than the form: an unchecked checkbox submits
 * nothing at all, so a form read by its own contents would silently drop every
 * switch somebody turned off.
 *
 * An `object` value returns `undefined` rather than falling through to text.
 * A text control renders one as `[object Object]` and would store that string,
 * which is worse than refusing; no shipped setting declares the type, and a
 * product that wants one needs a control before it needs a parser.
 */
export function parseSubmitted(definition: FormDefinition, raw: unknown): unknown {
  if (definition.data_type === 'boolean') return raw !== null && raw !== 'false'
  if (raw === null || raw === undefined) return undefined
  const text = String(raw)

  if (definition.data_type === 'integer') {
    const parsed = Number.parseInt(text, 10)
    return Number.isFinite(parsed) ? parsed : undefined
  }
  if (definition.data_type === 'decimal') {
    const parsed = Number.parseFloat(text)
    return Number.isFinite(parsed) ? parsed : undefined
  }
  if (definition.data_type === 'string_list') {
    return text
      .split(',')
      .map((entry) => entry.trim())
      .filter((entry) => entry !== '')
  }
  if (definition.data_type === 'object') return undefined
  return text
}

/**
 * One category's submitted values — and only the ones somebody changed.
 *
 * **Only what changed, and that is SET-05.** Every non-boolean control renders
 * with a `defaultValue`, so every one of them submits on every save; a walk
 * over the definitions that wrote what it was given therefore wrote the entire
 * category. A member who changed their theme also got a personal row for
 * density, landing page and sidebar — permanently detached from their
 * organisation's defaults for settings they never touched.
 *
 * What a field was rendered with arrives in a hidden `__baseline.<key>`, and a
 * value equal to its baseline is left out. **The baseline comes from the
 * browser**, so a tampered one can suppress a write the sender wanted or force
 * a redundant one. Neither escalates anything: this only ever *omits* a key,
 * never adds or alters one, and every surviving value still passes the API's
 * scope check, coercion and permission check.
 *
 * A form with no baselines at all — an older cached page — writes everything,
 * which is the previous behaviour and the safe direction to fail in.
 *
 * **What this gives up, stated rather than discovered.** A person can no
 * longer *create* an override whose value equals the one they are inheriting;
 * the save looks identical to not having touched the field. An override they
 * already hold is untouched, because an unchanged field is simply not
 * rewritten and the row stays. The two states differ only if the organisation
 * later changes that setting, and the page offers no other way to say "pin
 * this".
 */
export function valuesForCategory<D extends FormDefinition>(
  definitions: D[],
  category: string,
  form: { get(name: string): unknown },
  visible: (definition: D) => boolean,
): Record<string, unknown> {
  const values: Record<string, unknown> = {}

  for (const definition of definitions) {
    if (definition.category !== category || !visible(definition)) continue

    const submitted = parseSubmitted(definition, form.get(definition.key))
    if (submitted === undefined) continue

    const rawBaseline = form.get(`${BASELINE_PREFIX}${definition.key}`)
    if (rawBaseline !== null && rawBaseline !== undefined) {
      if (same(submitted, parseSubmitted(definition, rawBaseline))) continue
    }

    values[definition.key] = submitted
  }

  return values
}
