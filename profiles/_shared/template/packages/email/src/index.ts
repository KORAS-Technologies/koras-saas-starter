/**
 * Mail is sent server-side, by `python-packages/koras-email`, and written in
 * the reader's language from the catalogue in `koras_email.i18n` -- the same
 * three languages `packages/i18n` speaks, typed the same way, kept on the
 * side that composes the message.
 *
 * This package is empty on purpose rather than unfinished. The address, the
 * transport credential and the decision to contact somebody all belong to the
 * API: a browser must never hold an SMTP credential, and a Next.js server
 * action that sent mail directly would be a second place that decides who gets
 * written to, diverging from the first the moment either changes.
 *
 * What would go here is a *client* for an API endpoint that sends — and there
 * is no such endpoint yet, because no generated application has a message to
 * send. Adding one before then would be guessing at its shape.
 *
 * If you are here because you need to send mail: add the endpoint to
 * `services/api`, give it `koras-email`, and import it from `packages/api-client`
 * like every other call.
 */
export {}
