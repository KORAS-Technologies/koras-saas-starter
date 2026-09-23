/**
 * Secret redaction for everything the doctor prints.
 *
 * The doctor holds every bootstrap credential in memory and talks to seven
 * providers, so a raw error message is the most likely way a secret escapes:
 * an API echoing a token back in a 401 body, a CLI writing a credential into
 * stderr, an exception whose message interpolates a header. Every failure
 * string therefore passes through here before it reaches the terminal.
 *
 * Two layers, because either alone leaks:
 *
 *  1. Value-based — the actual secret values from the environment are replaced
 *     wherever they appear. This catches a provider quoting a token back at us.
 *  2. Pattern-based — anything *shaped* like a credential (a bearer token, a
 *     `TOKEN=...` assignment, a PEM block, a JWT) is replaced even if it never
 *     came from our environment.
 */

const REDACTED = '[redacted]'

/** Environment variable names whose values must never appear in output. */
const SENSITIVE_NAME = new RegExp(
  ['TOKEN', 'PASSWORD', 'SECRET', 'PRIVATE_KEY', 'API_KEY', 'SERVICE_ACCOUNT',
   'CREDENTIAL', 'AUTHORIZATION', 'JWT', 'COOKIE'].join('|'),
)

export function isSensitiveName(name: string): boolean {
  return SENSITIVE_NAME.test(name.toUpperCase())
}

/**
 * Values short enough to appear coincidentally are skipped — redacting every
 * occurrence of a 3-character value would corrupt the message without
 * protecting anything.
 */
const MIN_REDACTABLE_LENGTH = 6

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** Secret-shaped constructs, redacted regardless of where they came from. */
const PATTERNS: Array<[RegExp, string]> = [
  // PEM blocks — check before anything else; they span lines.
  [/-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----/g, REDACTED],
  // JWTs: three base64url segments. Also covers ZITADEL client assertions.
  [/\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]+/g, REDACTED],
  // Authorization headers, in any casing, quoted or not. The optional
  // `Bearer` is consumed as part of the scheme so the token after it is what
  // gets replaced — not the word "Bearer" itself.
  [
    /\b(authorization)\s*[:=]\s*["']?(?:bearer|basic|token)?\s*[A-Za-z0-9._~+/-]{6,}=*["']?/gi,
    `$1: ${REDACTED}`,
  ],
  [/\bbearer\s+[A-Za-z0-9._~+/-]{6,}=*/gi, `Bearer ${REDACTED}`],
  // Provider token prefixes. These are recognisable on sight, so they are
  // redacted even when the value never came from our own environment — an API
  // quoting someone else's token back is still a leak.
  [
    // `sk_`/`rk_` and `whsec_` are the payment provider's. Added when the
    // factory gained a step that holds one: a provider quoting a key back in a
    // 401 body was previously caught only by the value layer, and only when the
    // caller happened to pass the environment holding it.
    /\b(?:gh[pousr]_|github_pat_|sbp_|dp\.(?:st|pt|sa)\.|FlyV1[_ ]|hcp\.|cf-|vercel_|[sr]k_(?:live|test)_|whsec_)[A-Za-z0-9._-]{8,}/g,
    REDACTED,
  ],
  // KEY=value assignments where the name looks sensitive (CLI stderr, env dumps).
  [
    /\b([A-Z0-9_]*(?:TOKEN|PASSWORD|SECRET|PRIVATE_KEY|API_KEY|CREDENTIAL|JWT|COOKIE)[A-Z0-9_]*)\s*[:=]\s*["']?[^\s"']{4,}["']?/g,
    `$1=${REDACTED}`,
  ],
  // JSON fields carrying a credential, e.g. {"key":"...","clientSecret":"..."}.
  [
    /"(\w*(?:key|token|secret|password|credential|assertion)\w*)"\s*:\s*"[^"]{4,}"/gi,
    `"$1": "${REDACTED}"`,
  ],
]

/**
 * Redacts a message before it is printed.
 *
 * `env` supplies the value-based layer; pass the same environment the checks
 * ran against so a leaked value is caught even when it looks unremarkable.
 */
export function redact(message: unknown, env: NodeJS.ProcessEnv = process.env): string {
  let text =
    message instanceof Error
      ? (message.stack ?? message.message)
      : typeof message === 'string'
        ? message
        : String(message)

  // Longest first: a short secret that is a substring of a longer one must not
  // partially redact it and leave the remainder visible.
  const values = Object.entries(env)
    .filter(([name, value]) => isSensitiveName(name) && (value?.length ?? 0) >= MIN_REDACTABLE_LENGTH)
    .map(([, value]) => value as string)
    .sort((a, b) => b.length - a.length)

  for (const value of values) {
    text = text.replace(new RegExp(escapeRegExp(value), 'g'), REDACTED)
  }

  for (const [pattern, replacement] of PATTERNS) {
    text = text.replace(pattern, replacement)
  }

  return text
}
