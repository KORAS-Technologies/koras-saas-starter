/**
 * Stands in for `app/dashboard/imports/actions.ts` under `node --test`.
 *
 * The real module is a `'use server'` file bound to the API client and
 * `next/cache`; a component test needs only the functions `ImportPanel`
 * calls, answered by whatever the test installs on `handlers`. Every call is
 * also recorded in `calls`, because the panel's first claim is
 * about what it does *not* ask for until a person acts, and a claim about
 * silence needs a log.
 */
export const calls = []

function unanswered(name) {
  return async (...args) => {
    calls.push({ name, args })
    return { status: 'error', message: `no handler installed for ${name}` }
  }
}

export const handlers = {
  listRuns: unanswered('listRuns'),
  requestSourceUpload: unanswered('requestSourceUpload'),
  completeSourceUpload: unanswered('completeSourceUpload'),
  checkSource: unanswered('checkSource'),
  startRun: unanswered('startRun'),
  analyseRun: unanswered('analyseRun'),
  saveMapping: unanswered('saveMapping'),
  validateRun: unanswered('validateRun'),
  commitRun: unanswered('commitRun'),
  listErrors: unanswered('listErrors'),
  allErrors: unanswered('allErrors'),
  cancelRun: unanswered('cancelRun'),
}

/** Installs answers and clears the log; returns the log for assertions. */
export function install(answers) {
  for (const name of Object.keys(handlers)) {
    const answer = answers[name]
    handlers[name] = async (...args) => {
      calls.push({ name, args })
      return answer === undefined
        ? { status: 'error', message: `no handler installed for ${name}` }
        : answer(...args)
    }
  }
  calls.length = 0
  return calls
}

export function listRuns() {
  return handlers.listRuns()
}
export function requestSourceUpload(input) {
  return handlers.requestSourceUpload(input)
}
export function completeSourceUpload(fileId, checksum) {
  return handlers.completeSourceUpload(fileId, checksum)
}
export function checkSource(fileId) {
  return handlers.checkSource(fileId)
}
export function startRun(input) {
  return handlers.startRun(input)
}
export function analyseRun(runId) {
  return handlers.analyseRun(runId)
}
export function saveMapping(runId, mapping) {
  return handlers.saveMapping(runId, mapping)
}
export function validateRun(runId) {
  return handlers.validateRun(runId)
}
export function commitRun(runId) {
  return handlers.commitRun(runId)
}
export function listErrors(runId) {
  return handlers.listErrors(runId)
}
export function allErrors(runId, expected) {
  return handlers.allErrors(runId, expected)
}
export function cancelRun(runId) {
  return handlers.cancelRun(runId)
}
