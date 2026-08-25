/**
 * String normalization that a regular expression should not be doing.
 *
 * `s.replace(/\/+$/, '')` reads as the obvious way to drop trailing slashes and
 * is quadratic on input that is mostly slashes: the engine restarts the `\/+`
 * match at every position before concluding there is no match anchored at the end.
 * CodeQL flags it as `js/polynomial-redos`, and it is right to -- the inputs
 * here come from Doppler and from a `--control-plane-url` flag, which are
 * operator-controlled rather than attacker-controlled, but "the value happens
 * to be trusted today" is not a property of the code.
 *
 * A backwards scan is linear and says exactly what it does.
 */

const SLASH = '/'.charCodeAt(0)

export function stripTrailingSlashes(value: string): string {
  let end = value.length
  while (end > 0 && value.charCodeAt(end - 1) === SLASH) end--
  return end === value.length ? value : value.slice(0, end)
}
