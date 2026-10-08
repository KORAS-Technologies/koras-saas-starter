/* global File, URL, setImmediate, setTimeout */
import { strict as assert } from 'node:assert'
import { afterEach, mock, test } from 'node:test'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { install, calls } from '../../../test-support/imports-actions.stub.mjs'
import { createContainer } from '../../../test-support/fake-dom.mjs'
import { importLabels } from './labels.ts'
import { ImportPanel } from './ImportPanel.tsx'
import { PENDING_KEY } from './source-state.ts'

/**
 * The import panel's state machine, driven through its own handlers. The server actions are the stub in `test-support`, so every
 * call the panel makes is on the record, and the first claim below is about
 * what it does *not* call: nothing until a person acts.
 *
 * The clicks, the keyboard, the real bucket and the worker belong to
 * `e2e/roundtrip/imports.spec.ts`; this file proves the transitions and what
 * each state renders, with the API's answers scripted.
 */

const labels = importLabels((key) => key)

const ACCOUNTS = {
  key: 'shop.customers',
  label_key: 'import.target.shop.customers',
  fields: [
    { name: 'name', label_key: 'f', kind: 'text', required: true, options: [] },
    { name: 'roles', label_key: 'f', kind: 'text', required: true, options: [] },
    { name: 'registration_number', label_key: 'f', kind: 'text', required: false, options: [] },
    { name: 'country', label_key: 'f', kind: 'text', required: false, options: [] },
  ],
  match_keys: ['registration_number', 'name'],
  operations: ['skip_duplicate'],
  formats: ['csv', 'xlsx'],
  max_rows: 5000,
  committable: true,
  version: 1,
  template_formats: ['csv', 'xlsx'],
  limits: { max_bytes: 10 * 1024 * 1024, max_rows: 5000 },
  predicts: true,
}
const CONTACTS = {
  ...ACCOUNTS,
  key: 'shop.orders',
  label_key: 'import.target.shop.orders',
  fields: [
    { name: 'name', label_key: 'f', kind: 'text', required: true, options: [] },
    { name: 'email', label_key: 'f', kind: 'email', required: true, options: [] },
    { name: 'account_id', label_key: 'f', kind: 'text', required: true, options: [] },
  ],
  match_keys: ['email'],
}
const TARGETS = [ACCOUNTS, CONTACTS]

function run(overrides) {
  return {
    id: 'run-1',
    target: 'shop.customers',
    status: 'created',
    operation: 'skip_duplicate',
    columns: ['Name', 'Roles', 'Registration Number', 'Country'],
    mapping: {},
    rows_total: 0,
    rows_valid: 0,
    errors_total: 0,
    errors_cut: false,
    error: null,
    requested_by: 'owner',
    committed_by: null,
    created_at: '2026-09-30T10:00:00Z',
    finished_at: null,
    format: 'csv',
    source_name: 'accounts.csv',
    rows_duplicate: 0,
    predicted: null,
    written: null,
    ...overrides,
  }
}

const ANALYSIS = {
  columns: ['Name', 'Roles', 'Registration Number', 'Country'],
  suggested: { Name: 'name', Roles: 'roles', 'Registration Number': 'registration_number', Country: 'country' },
  preview: [{ Name: 'Acme Ltd', Roles: 'customer', 'Registration Number': 'HRB 1', Country: 'de' }],
  rows_seen: 3,
  over_ceiling: false,
  replaced: false,
  format: 'csv',
  sheet: null,
  template: { verdict: 'compatible', missing_required: [], unknown_columns: [], version_found: 1, stale: false },
}

/** Every mounted root, unmounted after each test whether it passed or not:
 *  a panel left mounted on an in-flight run keeps its polling timer, and a
 *  timer keeps the process alive after a failing assertion. */
const mounted = []

afterEach(async () => {
  for (const unmount of mounted.splice(0)) await unmount()
})

async function mount(props) {
  const container = createContainer()
  const root = createRoot(container)
  await act(async () =>
    root.render(createElement(ImportPanel, { targets: TARGETS, initialRuns: [], labels, ...props })),
  )
  const unmount = () => act(async () => root.unmount())
  mounted.push(unmount)
  return { container, unmount: async () => {} }
}

function reactProps(node) {
  assert.ok(node !== undefined, 'the control is not on the page')
  const key = Object.keys(node).find((name) => name.startsWith('__reactProps$'))
  assert.ok(key !== undefined, 'the node carries no React props')
  return node[key]
}

/** Activates a node's React `onClick`; `fake-dom.mjs` delivers no events. */
async function press(node) {
  const props = reactProps(node)
  await act(async () => {
    props.onClick({ currentTarget: node })
  })
  await act(async () => {})
}

async function change(node, target) {
  const props = reactProps(node)
  await act(async () => {
    props.onChange({ target })
  })
  await act(async () => {})
}

function all(container) {
  return [...container.descendants()]
}

/**
 * Lets the panel's async work run until `done()` is true, or fails.
 *
 * Choosing a file starts a chain -- the digest, the ticket, the PUT, the
 * completion, the run, the analysis -- and each link resolves on its own
 * turn. One `act` used to be enough on a developer machine and was not on a
 * CI runner (GR-344 S6, run 36875460961), so the tests wait for the state
 * they assert on rather than for a number of turns.
 */
async function settle(done, what) {
  for (let turn = 0; turn < 200; turn += 1) {
    if (done()) return
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 5))
    })
  }
  assert.fail(`the panel never reached: ${what}`)
}

function byId(container, id) {
  return all(container).find((node) => node.getAttribute?.('id') === id)
}

function buttonNamed(container, text) {
  return all(container).find((node) => node.tagName === 'BUTTON' && node.textContent === text)
}

function selectedValue(select) {
  return select.getAttribute('value') ?? reactProps(select).value
}

function options(select) {
  return all(select)
    .filter((node) => node.tagName === 'OPTION')
    .map((node) => ({ value: node.getAttribute('value'), text: node.textContent }))
}

/** A file the way a browser hands one over: name, size, type, bytes. */
function csvFile(name, text) {
  return new File([text], name, { type: 'text/csv' })
}

/**
 * The bucket, as the panel's `put` sees it: a `fetch` PUT answered with the
 * given status. Installed per test and restored after it, because the panel
 * reaches the bucket with the platform's `fetch` and nothing else.
 */
function fakeBucket(status = 200) {
  const puts = []
  const before = globalThis.fetch
  globalThis.fetch = async (url, init) => {
    puts.push({ method: init?.method, url, headers: init?.headers ?? {}, body: init?.body })
    return { ok: status >= 200 && status < 300, status }
  }
  mounted.push(async () => {
    globalThis.fetch = before
  })
  return puts
}

/** The sentence under the result card's heading: the run's state, as the page words it. */
function stateText(container) {
  return container.byTestId('imports-state')[0].textContent
}

test('the first paint calls nothing: the two reads are the page\'s, and no mutation waits on a render', async () => {
  const log = install({})
  const { container, unmount } = await mount({})
  assert.deepEqual(log, [], 'the panel asked the server for something before anybody acted')
  assert.equal(container.byTestId('imports-panel').length, 1)
  assert.equal(container.byTestId('imports-confirm').length, 0, 'no confirm control without a checked run')
  assert.equal(container.byTestId('imports-preview').length, 0)
  assert.ok(all(container).some((node) => node.textContent === 'imports.noRuns'))
  await unmount()
})

test('the Existing records hint is drawn below its control and describes it, and the target field has no hint', async () => {
  const { container } = await mount({})
  const nodes = all(container)
  const operation = nodes.find((n) => n.id === 'import-operation')
  const hint = nodes.find((n) => n.id === 'import-operation-hint')
  assert.ok(operation && hint, 'the operation select and its hint must both render')
  assert.equal(hint.textContent, labels.operationHint)
  assert.equal(operation.getAttribute('aria-describedby'), 'import-operation-hint')
  // Same frame: the hint is a later sibling of the control's wrapper, so the
  // control sits directly under its label and level with its neighbour's.
  const frame = operation.parentElement.parentElement
  const kids = [...frame.children]
  assert.equal(kids[0].localName, 'label')
  assert.ok(kids.indexOf(hint) > kids.indexOf(operation.parentElement), 'the hint must follow the control')
  const target = nodes.find((n) => n.id === 'import-target')
  assert.equal(target.getAttribute('aria-describedby'), null)
  assert.equal(nodes.filter((n) => n.id === 'import-target-hint').length, 0)
})

test('the picker lists the targets the API returned, keyed by their stable keys', async () => {
  install({})
  const { container, unmount } = await mount({})
  const picker = byId(container, 'import-target')
  assert.deepEqual(options(picker), [
    { value: 'shop.customers', text: 'shop.customers' },
    { value: 'shop.orders', text: 'shop.orders' },
  ])
  // The fixture targets declare one operation; it is the one shown.
  assert.deepEqual(options(byId(container, 'import-operation')), [
    { value: 'skip_duplicate', text: 'imports.op.skipDuplicate' },
  ])
  await unmount()
})

test('the template menu offers Excel then CSV from the canonical route, and no JSON', async () => {
  install({})
  const { container, unmount } = await mount({})
  const anchors = all(container).filter((node) => node.tagName === 'A' && String(node.getAttribute('href')).includes('/template'))
  assert.deepEqual(
    anchors.map((node) => node.getAttribute('href')),
    [
      '/api/imports/shop.customers/template?format=xlsx',
      '/api/imports/shop.customers/template?format=csv',
    ],
  )
  assert.deepEqual(
    anchors.map((node) => node.textContent),
    ['imports.template.xlsx', 'imports.template.csv'],
  )
  // The ceiling the API resolved -- the organisation's own limit inside the
  // framework's -- not a number the page keeps.
  const limits = container.byTestId('imports-limits')[0]
  assert.equal(limits.textContent, 'imports.limits')
  await unmount()
})

test('changing the target changes which template the menu points at', async () => {
  install({})
  const { container, unmount } = await mount({})
  await change(byId(container, 'import-target'), { value: 'shop.orders' })
  const anchors = all(container).filter((node) => node.tagName === 'A' && String(node.getAttribute('href')).includes('/template'))
  assert.deepEqual(
    anchors.map((node) => node.getAttribute('href')),
    [
      '/api/imports/shop.orders/template?format=xlsx',
      '/api/imports/shop.orders/template?format=csv',
    ],
  )
  await unmount()
})

test('choosing a file uploads it, starts a run, reads the analysis and prefills the mapping the API suggested', async () => {
  const puts = fakeBucket()
  const started = run({ status: 'created' })
  const log = install({
    requestSourceUpload: async () => ({
      status: 'ok',
      value: { file_id: 'file-1', upload_url: 'https://bucket.test/put', method: 'PUT', headers: { 'x-amz-meta': 'a' }, expires_in: 60 },
    }),
    completeSourceUpload: async () => ({ status: 'ok', value: null }),
    checkSource: async () => ({ status: 'ok', value: 'ready' }),
    startRun: async () => ({ status: 'ok', value: started }),
    analyseRun: async () => ({ status: 'ok', value: ANALYSIS }),
    listRuns: async () => ({ status: 'ok', value: [started] }),
  })
  const { container, unmount } = await mount({})
  await change(byId(container, 'import-file'), { files: [csvFile('accounts.csv', 'Name,Roles\nAcme,customer\n')] })
  await settle(() => log.some((entry) => entry.name === 'listRuns'), 'the run started and the history refreshed')

  assert.deepEqual(
    log.map((entry) => entry.name),
    ['requestSourceUpload', 'completeSourceUpload', 'checkSource', 'startRun', 'analyseRun', 'listRuns'],
  )
  // The category is not the browser's to choose: the action decides `imports`.
  assert.deepEqual(Object.keys(log[0].args[0]).sort(), ['checksumSha256', 'contentType', 'name', 'sizeBytes'])
  assert.equal(log[0].args[0].name, 'accounts.csv')
  assert.equal(log[0].args[0].contentType, 'text/csv')
  assert.match(String(log[0].args[0].checksumSha256), /^[0-9a-f]{64}$/)
  assert.equal(log[1].args[1], log[0].args[0].checksumSha256, 'completion carries the claim that was sent')
  assert.equal(puts.length, 1)
  assert.equal(puts[0].method, 'PUT')
  assert.equal(puts[0].url, 'https://bucket.test/put')
  assert.equal(puts[0].headers['x-amz-meta'], 'a')
  assert.equal(log[2].args[0], 'file-1')
  assert.deepEqual(log[3].args[0], { target: 'shop.customers', fileId: 'file-1', operation: 'skip_duplicate' })

  // The analysis prefilled every column the API matched, and the mapping
  // controls show it -- nothing in the browser matched a heading.
  assert.equal(selectedValue(byId(container, 'import-map-Name')), 'name')
  assert.equal(selectedValue(byId(container, 'import-map-Registration Number')), 'registration_number')
  assert.equal(selectedValue(byId(container, 'import-map-Country')), 'country')
  assert.equal(container.byTestId('imports-verdict')[0].getAttribute('data-verdict'), 'compatible')
  assert.ok(buttonNamed(container, 'imports.check'), 'the Check control is offered once a run is mapped')
  assert.equal(container.byTestId('imports-confirm').length, 0, 'no confirm before a dry run')
  await unmount()
})

const XLSX_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

test('the file type the browser reports is the one the ticket is asked for', async () => {
  for (const [file, expected] of [
    [new File(['PK'], 'a.xlsx', { type: XLSX_TYPE }), XLSX_TYPE],
    [new File(['Name,Roles'], 'a.csv', { type: 'text/csv' }), 'text/csv'],
  ]) {
    fakeBucket()
    const started = run({ status: 'created' })
    const log = install({
      requestSourceUpload: async () => ({
        status: 'ok',
        value: { file_id: 'file-1', upload_url: 'https://bucket.test/put', method: 'PUT', headers: {}, expires_in: 60 },
      }),
      completeSourceUpload: async () => ({ status: 'ok', value: null }),
      checkSource: async () => ({ status: 'ok', value: 'ready' }),
      startRun: async () => ({ status: 'ok', value: started }),
      analyseRun: async () => ({ status: 'ok', value: ANALYSIS }),
      listRuns: async () => ({ status: 'ok', value: [started] }),
    })
    const { container, unmount } = await mount({})
    await change(byId(container, 'import-file'), { files: [file] })
    await settle(() => log.some((entry) => entry.name === 'listRuns'), 'the run started')
    assert.equal(log[0].args[0].contentType, expected)
    await unmount()
  }
})

test('a file the scanner has not cleared is refused where the run would start, in the API\'s words, and nothing continues', async () => {
  fakeBucket()
  const log = install({
    requestSourceUpload: async () => ({
      status: 'ok',
      value: { file_id: 'file-2', upload_url: 'https://bucket.test/put', method: 'PUT', headers: {}, expires_in: 60 },
    }),
    completeSourceUpload: async () => ({ status: 'ok', value: null }),
    checkSource: async () => ({ status: 'ok', value: 'ready' }),
    startRun: async () => ({ status: 'error', message: 'errors.fileQuarantined' }),
  })
  const { container, unmount } = await mount({})
  await change(byId(container, 'import-file'), { files: [csvFile('pending.csv', 'Name\nAcme\n')] })
  await settle(
    () => all(container).some((node) => node.textContent === 'errors.fileQuarantined'),
    'the refusal shown',
  )
  assert.deepEqual(log.map((entry) => entry.name), ['requestSourceUpload', 'completeSourceUpload', 'checkSource', 'startRun'])
  assert.ok(all(container).some((node) => node.textContent === 'errors.fileQuarantined'), 'the refusal is shown')
  assert.equal(byId(container, 'import-map-Name'), undefined, 'no mapping card for a run that never started')
  await unmount()
})


// -- a file that is still being checked is a wait, not a refusal ------------------
//
// The DEV defect: a workbook chosen a moment ago was withheld (a new upload is
// not finalized or scanned for most of twenty minutes), the run was started
// anyway, and the refusal read "This file is not available." beside the name of
// a perfectly good file. The page now asks where the source is and starts the
// run only when the server says `ready`.

const xlsxFile = (name) => new File(['PK-workbook'], name, { type: XLSX_TYPE })

const STORE = new Map()

function withStorage() {
  const before = globalThis.window
  globalThis.window = {
    ...(before ?? {}),
    localStorage: {
      getItem: (key) => (STORE.has(key) ? STORE.get(key) : null),
      setItem: (key, value) => void STORE.set(key, String(value)),
      removeItem: (key) => void STORE.delete(key),
      get length() {
        return STORE.size
      },
      key: (at) => [...STORE.keys()][at] ?? null,
    },
  }
  STORE.clear()
  mounted.push(async () => {
    if (before === undefined) delete globalThis.window
    else globalThis.window = before
    STORE.clear()
  })
}

/** Lets pending promises and React effects run without touching timers. */
async function flush(turns = 40) {
  for (let turn = 0; turn < turns; turn += 1) {
    await act(async () => {
      await new Promise((resolve) => setImmediate(resolve))
    })
  }
}

/** Runs the event loop until `done()` is true; setImmediate is never mocked. */
async function flushUntil(done, what = 'the awaited state') {
  for (let turn = 0; turn < 3000; turn += 1) {
    if (done()) return
    await act(async () => {
      await new Promise((resolve) => setImmediate(resolve))
    })
  }
  assert.fail(`the panel never reached: ${what}`)
}

const sourceShown = (container) => () => container.byTestId('imports-source').length > 0

function uploadScript(answer, extra = {}) {
  return {
    requestSourceUpload: async () => ({
      status: 'ok',
      value: { file_id: 'file-9', upload_url: 'https://bucket.test/put', method: 'PUT', headers: {}, expires_in: 60 },
    }),
    completeSourceUpload: async () => ({ status: 'ok', value: null }),
    checkSource: answer,
    startRun: async () => ({ status: 'ok', value: run({ status: 'created' }) }),
    analyseRun: async () => ({ status: 'ok', value: ANALYSIS }),
    listRuns: async () => ({ status: 'ok', value: [run({ status: 'created' })] }),
    ...extra,
  }
}

const names = (log) => log.map((entry) => entry.name).filter((name) => name !== 'listRuns')

test('a file still being checked is waited for: no run, no refusal, and the run starts when the server says ready', async () => {
  withStorage()
  fakeBucket()
  let state = 'checking'
  const log = install(uploadScript(async () => ({ status: 'ok', value: state })))
  mock.timers.enable({ apis: ['setTimeout'] })
  try {
    const { container } = await mount({})
    await change(byId(container, 'import-file'), { files: [xlsxFile('accounts.xlsx', 'Name\nAcme\n')] })
    await flushUntil(() => names(log).includes('checkSource'), 'the first ask')

    assert.deepEqual(names(log), ['requestSourceUpload', 'completeSourceUpload', 'checkSource'])
    const source = container.byTestId('imports-source')[0]
    assert.equal(source.getAttribute('data-phase'), 'checking')
    assert.equal(source.textContent.includes('imports.source.checking'), true)
    // Announced politely, as a status, not as an alert.
    assert.ok(all(source).some((node) => node.getAttribute?.('role') === 'status'), 'the wait is a status banner')
    assert.equal(all(source).some((node) => node.getAttribute?.('role') === 'alert'), false)
    assert.equal(container.textContent.includes('errors.fileQuarantined'), false, 'a wait is not a quarantine')
    assert.equal(container.textContent.includes('errors.fileScanPending'), false)
    assert.ok(buttonNamed(container, 'imports.source.stop'), 'the person can stop waiting')
    assert.ok(STORE.get(PENDING_KEY)?.includes('file-9'), 'the wait is remembered')

    // Ten seconds later it is still being checked: still no run.
    await act(async () => mock.timers.tick(10_000))
    await flush()
    assert.equal(names(log).filter((name) => name === 'startRun').length, 0)

    // The server clears it; the next ask starts the run on its own.
    state = 'ready'
    await act(async () => mock.timers.tick(20_000))
    await flush()
    assert.deepEqual(names(log).slice(-3), ['checkSource', 'startRun', 'analyseRun'])
    assert.equal(container.byTestId('imports-source').length, 0, 'the wait is over')
    assert.equal(STORE.has(PENDING_KEY), false, 'nothing left to resume')
    assert.ok(byId(container, 'import-map-Name'), 'the mapping card is drawn')
  } finally {
    mock.timers.reset()
  }
})

for (const [state, sentence] of [
  ['held', 'imports.source.held'],
  ['rejected', 'imports.source.rejected'],
  ['missing', 'imports.source.missing'],
]) {
  test(`a source the server calls ${state} ends the wait with its own sentence and starts nothing`, async () => {
    withStorage()
    fakeBucket()
    const log = install(uploadScript(async () => ({ status: 'ok', value: state })))
    const { container } = await mount({})
    await change(byId(container, 'import-file'), { files: [xlsxFile('accounts.xlsx', 'Name\nAcme\n')] })
    await flushUntil(() => container.byTestId('imports-source')[0]?.getAttribute('data-phase') === state, state)
    assert.equal(container.byTestId('imports-source')[0].getAttribute('data-phase'), state)
    assert.equal(container.byTestId('imports-source')[0].textContent.includes(sentence), true)
    // Held is a status; a rejected or missing source is an error and is announced as one.
    const role = state === 'held' ? 'status' : 'alert'
    assert.ok(
      all(container.byTestId('imports-source')[0]).some((node) => node.getAttribute?.('role') === role),
      `the ${state} sentence is a ${role}`,
    )
    assert.equal(names(log).includes('startRun'), false)
    assert.equal(STORE.has(PENDING_KEY), false)
  })
}

test('a source the server does not recognise is never treated as ready', async () => {
  withStorage()
  fakeBucket()
  const log = install(uploadScript(async () => ({ status: 'ok', value: 'something-new' })))
  const { container } = await mount({})
  await change(byId(container, 'import-file'), { files: [xlsxFile('accounts.xlsx', 'Name\nAcme\n')] })
  await flushUntil(() => container.byTestId('imports-source')[0]?.getAttribute('data-phase') === 'missing', 'missing')
  assert.equal(names(log).includes('startRun'), false)
  assert.equal(container.byTestId('imports-source')[0].getAttribute('data-phase'), 'missing')
})

test('a wait that outlives the page stops asking, says the check is slow, and offers Check again', async () => {
  withStorage()
  fakeBucket()
  let state = 'checking'
  const log = install(uploadScript(async () => ({ status: 'ok', value: state })))
  mock.timers.enable({ apis: ['setTimeout', 'Date'] })
  try {
    const { container } = await mount({})
    await change(byId(container, 'import-file'), { files: [xlsxFile('accounts.xlsx', 'Name\nAcme\n')] })
    await flushUntil(() => names(log).includes('checkSource'), 'the first ask')
    await act(async () => mock.timers.tick(46 * 60_000))
    await flush()
    assert.equal(container.byTestId('imports-source')[0].getAttribute('data-phase'), 'stalled')
    const asked = names(log).length
    await act(async () => mock.timers.tick(5 * 60_000))
    await flush()
    assert.equal(names(log).length, asked, 'a stalled page does not keep asking')

    state = 'ready'
    await press(buttonNamed(container, 'imports.source.checkAgain'))
    await flush()
    assert.equal(names(log).includes('startRun'), true)
  } finally {
    mock.timers.reset()
  }
})

test('Check again while the file is still being checked keeps the button mounted, stays stalled, and says it looked', async () => {
  withStorage()
  fakeBucket()
  const log = install(uploadScript(async () => ({ status: 'ok', value: 'checking' })))
  mock.timers.enable({ apis: ['setTimeout', 'Date'] })
  try {
    const { container } = await mount({})
    await change(byId(container, 'import-file'), { files: [xlsxFile('accounts.xlsx', 'Name\nAcme\n')] })
    await flushUntil(() => names(log).includes('checkSource'), 'the first ask')
    await act(async () => mock.timers.tick(46 * 60_000))
    await flush()
    const button = buttonNamed(container, 'imports.source.checkAgain')
    const asked = names(log).filter((name) => name === 'checkSource').length
    await press(button)
    await flush()
    assert.equal(names(log).filter((name) => name === 'checkSource').length, asked + 1, 'it looked once')
    assert.equal(container.byTestId('imports-source')[0].getAttribute('data-phase'), 'stalled')
    assert.equal(container.byTestId('imports-source-rechecked').length, 1, 'and said so')
    assert.equal(buttonNamed(container, 'imports.source.checkAgain'), button, 'the same button, still mounted')
    await act(async () => mock.timers.tick(5 * 60_000))
    await flush()
    assert.equal(names(log).filter((name) => name === 'checkSource').length, asked + 1, 'one look is not polling')
  } finally {
    mock.timers.reset()
  }
})

test('the status region for the wait is always mounted, so a change in it is announced', async () => {
  withStorage()
  fakeBucket()
  install(uploadScript(async () => ({ status: 'ok', value: 'checking' })))
  const { container } = await mount({})
  const live = () => container.byTestId('imports-source-live')[0]
  assert.equal(live().getAttribute('role'), 'status')
  assert.equal(container.byTestId('imports-source').length, 0)
  await change(byId(container, 'import-file'), { files: [xlsxFile('accounts.xlsx', 'Name\nAcme\n')] })
  await flushUntil(() => container.byTestId('imports-source').length === 1, 'the wait shown')
  assert.equal(live().getAttribute('role'), 'status', 'the same element, not a new one')
})

test('a flaky look is a quiet note beside the wait, not a page-level alert', async () => {
  withStorage()
  fakeBucket()
  install(uploadScript(async () => ({ status: 'error', message: 'imports.error.unavailable', final: false })))
  const { container } = await mount({})
  await change(byId(container, 'import-file'), { files: [xlsxFile('accounts.xlsx')] })
  await flushUntil(() => container.byTestId('imports-source-retry').length === 1, 'the note')
  assert.equal(container.byTestId('imports-source-retry')[0].textContent.includes('imports.source.unreachable'), true)
  assert.equal(all(container).filter((el) => el.getAttribute('role') === 'alert').length, 0)
})

test('stopping the wait forgets the file and clears the page', async () => {
  withStorage()
  fakeBucket()
  install(uploadScript(async () => ({ status: 'ok', value: 'checking' })))
  const { container } = await mount({})
  await change(byId(container, 'import-file'), { files: [xlsxFile('accounts.xlsx', 'Name\nAcme\n')] })
  await flushUntil(() => STORE.size === 1, 'the wait remembered')
  assert.equal(STORE.size, 1)
  await press(buttonNamed(container, 'imports.source.stop'))
  assert.equal(container.byTestId('imports-source').length, 0)
  assert.equal(STORE.size, 0)
})

test('a person who left while the file was being checked comes back to it; found ready, it waits for a click to start', async () => {
  withStorage()
  STORE.set(
    PENDING_KEY,
    JSON.stringify({
      fileId: 'file-7',
      name: 'accounts.xlsx',
      size: 13670,
      target: 'shop.customers',
      operation: 'skip_duplicate',
      at: Date.now() - 20 * 60_000,
    }),
  )
  const log = install(uploadScript(async () => ({ status: 'ok', value: 'ready' })))
  const { container } = await mount({})
  await flush()
  assert.deepEqual(names(log), ['checkSource'], 'a restored wait never starts a run by itself')
  assert.equal(log[0].args[0], 'file-7')
  assert.equal(container.byTestId('imports-source')[0].getAttribute('data-phase'), 'ready')
  await press(buttonNamed(container, 'imports.source.continue'))
  await flush()
  assert.deepEqual(names(log).slice(0, 3), ['checkSource', 'startRun', 'analyseRun'])
  assert.equal(log.find((entry) => entry.name === 'startRun').args[0].fileId, 'file-7')
  assert.equal(names(log).includes('requestSourceUpload'), false, 'nothing is uploaded a second time')
  assert.equal(STORE.size, 0)
})

test('a wait remembered by one person is invisible to another, and opening the page as someone else forgets it', async () => {
  withStorage()
  STORE.set(
    `${PENDING_KEY}:org-1:user-1`,
    JSON.stringify({ fileId: 'file-7', name: 'secret.xlsx', size: 1, target: 'shop.customers', operation: 'skip_duplicate', at: Date.now() }),
  )
  const log = install(uploadScript(async () => ({ status: 'ok', value: 'ready' })))
  const { container } = await mount({ storageScope: 'org-1:user-2' })
  await flush()
  assert.deepEqual(log, [])
  assert.equal(container.textContent.includes('secret.xlsx'), false)
  assert.equal(STORE.size, 0, "the previous person's entry is not left behind on the browser")
  await mounted.pop()?.()
  await mount({ storageScope: 'org-1:user-1' })
  await flush()
  assert.deepEqual(log, [], 'and it is not offered back to the first person either')
})

test('switching organisation forgets the wait, the runs and the mapping of the one left', async () => {
  withStorage()
  STORE.set(
    `${PENDING_KEY}:org-1:user-1`,
    JSON.stringify({ fileId: 'file-7', name: 'org-one.xlsx', size: 1, target: 'shop.customers', operation: 'skip_duplicate', at: Date.now() }),
  )
  // A stray entry under the bare key (an older build) and under another scope.
  STORE.set(PENDING_KEY, '{}')
  STORE.set('unrelated.key', 'kept')
  const log = install(uploadScript(async () => ({ status: 'ok', value: 'checking' })))
  const first = await mount({ storageScope: 'org-1:user-1', initialRuns: [run({ id: 'run-of-org-1' })] })
  await flush()
  assert.equal(first.container.byTestId('imports-source')[0].getAttribute('data-phase'), 'checking')
  await mounted.pop()?.()
  // The page re-keys the panel on the scope, so a switch is an unmount and a fresh mount.
  const second = await mount({ storageScope: 'org-2:user-1', initialRuns: [] })
  await flush()
  assert.equal(second.container.byTestId('imports-source').length, 0, 'the wait did not follow the person')
  assert.equal(second.container.textContent.includes('org-one.xlsx'), false)
  assert.equal(second.container.textContent.includes('run-of-org-1'), false)
  assert.deepEqual([...STORE.keys()], ['unrelated.key'], 'only the pending-wait entries are touched')
  assert.equal(log.filter((entry) => entry.name === 'checkSource').length, 1, 'nothing asked on behalf of org-2')
})

const focused = (container) => container.ownerDocument.activeElement

test('Stop pressed while the chooser is still disabled hands focus to the chooser once it is enabled', async () => {
  withStorage()
  fakeBucket()
  let release
  const gate = new Promise((resolve) => {
    release = resolve
  })
  install(uploadScript(async () => (await gate, { status: 'ok', value: 'checking' })))
  const { container } = await mount({})
  await change(byId(container, 'import-file'), { files: [xlsxFile('accounts.xlsx', 'Name\nAcme\n')] })
  await flushUntil(() => buttonNamed(container, 'imports.source.stop') !== undefined, 'Stop shown')
  const chooser = byId(container, 'import-file')
  assert.equal(chooser.getAttribute('disabled') !== null, true, 'the chooser is disabled while the first look is made')
  await press(buttonNamed(container, 'imports.source.stop'))
  assert.notEqual(focused(container), chooser, 'a disabled control cannot take focus')
  release()
  await flushUntil(() => byId(container, 'import-file').getAttribute('disabled') === null, 'the chooser enabled')
  await flush()
  assert.equal(focused(container), byId(container, 'import-file'), 'focus is on the file chooser')
})

test('Stop pressed with the chooser enabled puts focus on it', async () => {
  withStorage()
  fakeBucket()
  install(uploadScript(async () => ({ status: 'ok', value: 'checking' })))
  const { container } = await mount({})
  await change(byId(container, 'import-file'), { files: [xlsxFile('accounts.xlsx', 'Name\nAcme\n')] })
  await flushUntil(() => byId(container, 'import-file').getAttribute('disabled') === null, 'settled')
  await press(buttonNamed(container, 'imports.source.stop'))
  await flush()
  assert.equal(focused(container), byId(container, 'import-file'))
})

test('Continue hands focus to the mapping heading, which is focusable but not a tab stop', async () => {
  withStorage()
  STORE.set(
    PENDING_KEY,
    JSON.stringify({ fileId: 'file-7', name: 'accounts.xlsx', size: 1, target: 'shop.customers', operation: 'skip_duplicate', at: Date.now() }),
  )
  install(uploadScript(async () => ({ status: 'ok', value: 'ready' })))
  const { container } = await mount({})
  await flush()
  const button = buttonNamed(container, 'imports.source.continue')
  await press(button)
  await flush()
  const heading = all(container).find((node) => node.tagName === 'H2' && node.textContent === labels.mapTitle)
  assert.ok(heading !== undefined, 'the mapping is drawn')
  assert.equal(heading.getAttribute('tabindex'), '-1')
  assert.equal(focused(container), heading, 'focus did not fall to the page when Continue left')
})

test('Continue that ends in a refusal puts focus on the chooser rather than on nothing', async () => {
  withStorage()
  STORE.set(
    PENDING_KEY,
    JSON.stringify({ fileId: 'file-7', name: 'accounts.xlsx', size: 1, target: 'shop.customers', operation: 'skip_duplicate', at: Date.now() }),
  )
  install(
    uploadScript(async () => ({ status: 'ok', value: 'ready' }), {
      startRun: async () => ({ status: 'error', message: 'refused', final: true }),
    }),
  )
  const { container } = await mount({})
  await flush()
  await press(buttonNamed(container, 'imports.source.continue'))
  await flush()
  assert.equal(focused(container), byId(container, 'import-file'))
})

async function stalledPanel(script) {
  withStorage()
  fakeBucket()
  let state = 'checking'
  const log = install(uploadScript(async () => (state === 'error' ? script.error : { status: 'ok', value: state })))
  mock.timers.enable({ apis: ['setTimeout', 'Date'] })
  const { container } = await mount({})
  await change(byId(container, 'import-file'), { files: [xlsxFile('accounts.xlsx', 'Name\nAcme\n')] })
  await flushUntil(() => names(log).includes('checkSource'), 'the first ask')
  await act(async () => mock.timers.tick(46 * 60_000))
  await flush()
  return { container, log, set: (next) => void (state = next) }
}

test('Check again that ends the wait hands focus on: the mapping when the file is ready, the chooser on a final refusal', async () => {
  try {
    const ready = await stalledPanel({})
    ready.set('ready')
    await press(buttonNamed(ready.container, 'imports.source.checkAgain'))
    await flush()
    const heading = all(ready.container).find((node) => node.tagName === 'H2' && node.textContent === labels.mapTitle)
    assert.ok(heading !== undefined)
    assert.equal(focused(ready.container), heading)
    await mounted.pop()?.()
    mock.timers.reset()

    const refused = await stalledPanel({ error: { status: 'error', message: 'errors.importFileTooLarge', final: true } })
    refused.set('error')
    await press(buttonNamed(refused.container, 'imports.source.checkAgain'))
    await flush()
    assert.equal(focused(refused.container), byId(refused.container, 'import-file'))
  } finally {
    mock.timers.reset()
  }
})

test('Check again that finds a restored file ready hands focus to the sentence that offers Continue', async () => {
  withStorage()
  let state = 'checking'
  install(uploadScript(async () => ({ status: 'ok', value: state })))
  mock.timers.enable({ apis: ['setTimeout', 'Date'] })
  try {
  STORE.set(
      PENDING_KEY,
      JSON.stringify({ fileId: 'file-7', name: 'accounts.xlsx', size: 1, target: 'shop.customers', operation: 'skip_duplicate', at: Date.now() }),
    )
    const { container } = await mount({})
    await flush()
    await act(async () => mock.timers.tick(46 * 60_000))
    await flush()
    state = 'ready'
    await press(buttonNamed(container, 'imports.source.checkAgain'))
    await flush()
    assert.equal(focused(container), container.byTestId('imports-source')[0])
    assert.ok(buttonNamed(container, 'imports.source.continue') !== undefined)
  } finally {
    mock.timers.reset()
  }
})

test('focus is not pulled from a control the person has moved to while the page was busy', async () => {
  withStorage()
  fakeBucket()
  let release
  const gate = new Promise((resolve) => {
    release = resolve
  })
  install(uploadScript(async () => (await gate, { status: 'ok', value: 'checking' })))
  const { container } = await mount({})
  await change(byId(container, 'import-file'), { files: [xlsxFile('accounts.xlsx', 'Name\nAcme\n')] })
  await flushUntil(() => buttonNamed(container, 'imports.source.stop') !== undefined, 'Stop shown')
  await press(buttonNamed(container, 'imports.source.stop'))
  const elsewhere = byId(container, 'import-target')
  elsewhere.focus()
  assert.equal(focused(container), elsewhere)
  release()
  await flushUntil(() => byId(container, 'import-file').getAttribute('disabled') === null, 'the chooser enabled')
  await flush()
  assert.equal(focused(container), elsewhere, 'the person keeps the control they chose')
})

test('starting a run says so in the status region while the control that asked is gone', async () => {
  withStorage()
  STORE.set(
    PENDING_KEY,
    JSON.stringify({ fileId: 'file-7', name: 'accounts.xlsx', size: 1, target: 'shop.customers', operation: 'skip_duplicate', at: Date.now() }),
  )
  let release
  const gate = new Promise((resolve) => {
    release = resolve
  })
  install(
    uploadScript(async () => ({ status: 'ok', value: 'ready' }), {
      startRun: async () => (await gate, { status: 'ok', value: run({ status: 'created' }) }),
    }),
  )
  const { container } = await mount({})
  await flush()
  await press(buttonNamed(container, 'imports.source.continue'))
  assert.equal(container.byTestId('imports-starting').length, 1)
  assert.equal(container.byTestId('imports-starting')[0].textContent, labels.starting)
  release()
  await flush()
  assert.equal(container.byTestId('imports-starting').length, 0)
})

test('a final refusal while asking ends the wait with the API\'s words instead of polling for forty-five minutes', async () => {
  withStorage()
  fakeBucket()
  const log = install(
    uploadScript(async () => ({ status: 'error', message: 'errors.importFileTooLarge', final: true })),
  )
  const { container } = await mount({})
  await change(byId(container, 'import-file'), { files: [xlsxFile('accounts.xlsx')] })
  await flushUntil(() => container.textContent.includes('errors.importFileTooLarge'), 'the refusal shown')
  assert.equal(container.textContent.includes('errors.importFileTooLarge'), true)
  assert.equal(container.byTestId('imports-source').length, 0)
  assert.equal(STORE.size, 0)
  assert.equal(names(log).includes('startRun'), false)
})

test('a transient failure while asking keeps the wait and says the check could not be made just now', async () => {
  withStorage()
  fakeBucket()
  const log = install(
    uploadScript(async () => ({ status: 'error', message: 'imports.error.unavailable', final: false })),
  )
  const { container } = await mount({})
  await change(byId(container, 'import-file'), { files: [xlsxFile('accounts.xlsx')] })
  await flushUntil(() => container.textContent.includes('imports.source.unreachable'), 'the unreachable sentence')
  assert.equal(container.byTestId('imports-source')[0].getAttribute('data-phase'), 'checking')
  assert.equal(STORE.size, 1)
  assert.equal(names(log).includes('startRun'), false)
})

test('an answer that arrives after Stop waiting is dropped and starts nothing', async () => {
  withStorage()
  fakeBucket()
  let release
  const gate = new Promise((resolve) => {
    release = resolve
  })
  const log = install(
    uploadScript(async () => {
      await gate
      return { status: 'ok', value: 'ready' }
    }),
  )
  const { container } = await mount({})
  await change(byId(container, 'import-file'), { files: [xlsxFile('accounts.xlsx')] })
  await flushUntil(sourceShown(container), 'the source banner')
  await press(buttonNamed(container, 'imports.source.stop'))
  release()
  await flush(100)
  assert.equal(names(log).includes('startRun'), false)
  assert.equal(container.byTestId('imports-source').length, 0)
})

test('a remembered file for a target this person cannot use, or older than a day, or garbled, is ignored', async () => {
  for (const stored of [
    JSON.stringify({ fileId: 'f', name: 'n', size: 1, target: 'other.target', operation: 'create', at: Date.now() }),
    JSON.stringify({ fileId: 'f', name: 'n', size: 1, target: 'shop.customers', operation: 'create', at: Date.now() - 25 * 3600_000 }),
    '{not json',
    JSON.stringify({ fileId: 7 }),
  ]) {
    withStorage()
    STORE.set(PENDING_KEY, stored)
    const log = install({})
    await mount({})
    await flush(5)
    assert.deepEqual(log, [], stored)
  }
})

test('Check saves the mapping the person left, asks for the dry run, and shows the run as checking', async () => {
  fakeBucket()
  const started = run({ status: 'created' })
  const queued = run({ status: 'validating' })
  // The history answers what the API would: the run as created until the
  // dry run is asked for, and as validating from then on.
  let asked = false
  const log = install({
    requestSourceUpload: async () => ({
      status: 'ok',
      value: { file_id: 'file-1', upload_url: 'https://bucket.test/put', method: 'PUT', headers: {}, expires_in: 60 },
    }),
    completeSourceUpload: async () => ({ status: 'ok', value: null }),
    checkSource: async () => ({ status: 'ok', value: 'ready' }),
    startRun: async () => ({ status: 'ok', value: started }),
    analyseRun: async () => ({ status: 'ok', value: ANALYSIS }),
    listRuns: async () => ({ status: 'ok', value: [asked ? queued : started] }),
    saveMapping: async () => ({ status: 'ok', value: run({ status: 'mapped' }) }),
    validateRun: async () => {
      asked = true
      return { status: 'ok', value: queued }
    },
  })
  const { container, unmount } = await mount({})
  await change(byId(container, 'import-file'), { files: [csvFile('accounts.csv', 'Name\nAcme\n')] })
  await settle(() => byId(container, 'import-map-Country') !== undefined, 'the mapping card drawn')
  // A person unmaps a column: the API is told exactly that.
  await change(byId(container, 'import-map-Country'), { value: '' })
  log.length = 0
  await press(buttonNamed(container, 'imports.check'))
  assert.deepEqual(log.map((entry) => entry.name), ['saveMapping', 'validateRun', 'listRuns'])
  assert.deepEqual(log[0].args, ['run-1', { Name: 'name', Roles: 'roles', 'Registration Number': 'registration_number' }])
  assert.equal(stateText(container), 'imports.state.validating')
  await unmount()
})

test('a checked run shows the predicted figures and an explicit confirm; confirming asks once and shows the run as queued', async () => {
  const validated = run({
    status: 'validated',
    rows_total: 3,
    rows_valid: 3,
    rows_duplicate: 0,
    predicted: { create: 2, update: 0, skip: 1 },
  })
  const queued = { ...validated, status: 'commit_requested', committed_by: 'owner' }
  const log = install({
    analyseRun: async () => ({ status: 'ok', value: ANALYSIS }),
    listRuns: async () => ({ status: 'ok', value: [queued] }),
    commitRun: async () => ({ status: 'ok', value: queued }),
  })
  const { container, unmount } = await mount({ initialRuns: [validated] })
  await press(container.byTestId('imports-open')[0])
  await flush(5)
  assert.deepEqual(log.map((entry) => entry.name), ['analyseRun'], 'opening reads the file for the review and writes nothing')
  assert.equal(container.byTestId('imports-preview-total')[0].textContent, 'imports.preview.total3')
  assert.equal(container.byTestId('imports-preview-create')[0].textContent, 'imports.preview.create2')
  assert.equal(container.byTestId('imports-preview-update')[0].textContent, 'imports.preview.update0')
  assert.equal(container.byTestId('imports-preview-skip')[0].textContent, 'imports.preview.skip1')
  assert.equal(container.byTestId('imports-preview-unknown').length, 0)
  assert.equal(container.byTestId('imports-confirm').length, 0, 'Review comes before Confirm')
  await press(buttonNamed(container, 'imports.review.continue'))
  assert.equal(container.byTestId('imports-confirm').length, 1)
  assert.equal(container.byTestId('imports-committed').length, 0, 'nothing claims success before a commit')

  await press(buttonNamed(container, 'imports.confirm'))
  assert.deepEqual(log.map((entry) => entry.name), ['analyseRun', 'commitRun', 'listRuns'])
  assert.equal(stateText(container), 'imports.state.commitRequested')
  assert.equal(container.byTestId('imports-confirm').length, 0, 'the confirm control leaves with the state')
  assert.equal(container.byTestId('imports-committed').length, 0, 'queued is not done')
  await unmount()
})

test('a second confirm the API refuses is shown as the refusal, not as an outcome', async () => {
  const validated = run({ status: 'validated', rows_total: 1, rows_valid: 1, predicted: { create: 1, update: 0, skip: 0 } })
  install({
    analyseRun: async () => ({ status: 'ok', value: ANALYSIS }),
    listRuns: async () => ({ status: 'ok', value: [validated] }),
    commitRun: async () => ({ status: 'error', message: 'errors.importNotTransitionable' }),
  })
  const { container, unmount } = await mount({ initialRuns: [validated] })
  await press(container.byTestId('imports-open')[0])
  await flush(5)
  await press(buttonNamed(container, 'imports.review.continue'))
  await press(buttonNamed(container, 'imports.confirm'))
  assert.ok(all(container).some((node) => node.textContent === 'errors.importNotTransitionable'))
  assert.equal(container.byTestId('imports-committed').length, 0)
  await unmount()
})

test('a run with problems lists them by file line from the structured report, and offers the download', async () => {
  const failed = run({
    id: 'run-9',
    target: 'shop.orders',
    status: 'validation_failed',
    rows_total: 4,
    rows_valid: 2,
    errors_total: 2,
  })
  install({
    listErrors: async () => ({
      status: 'ok',
      value: [
        { cursor: 1, row: 3, column: 'Email', field: 'email', code: 'import.error.required', value: '' },
        { cursor: 2, row: 5, column: 'Account', field: 'customer_id', code: 'import.error.shop.customer_id', value: 'nope' },
      ],
    }),
  })
  const { container, unmount } = await mount({ initialRuns: [failed] })
  await press(container.byTestId('imports-open')[0])
  assert.equal(container.byTestId('imports-confirm').length, 0, 'a failed check cannot be confirmed')
  assert.equal(container.byTestId('imports-preview-invalid')[0].textContent, 'imports.preview.invalid2')
  assert.ok(buttonNamed(container, 'imports.downloadReport'))
  await press(buttonNamed(container, 'imports.showReport'))
  const table = all(container).find(
    (node) => node.tagName === 'TABLE' && all(node).some((cell) => cell.tagName === 'TH' && cell.textContent === labels.problem),
  )
  assert.ok(table !== undefined, 'the problems table is drawn')
  const rows = all(table).filter((node) => node.tagName === 'TR').slice(1)
  assert.deepEqual(
    rows.map((tr) => all(tr).filter((node) => node.tagName === 'TD').map((td) => td.textContent)),
    [
      ['3', 'Email', 'imports.problem.required', ''],
      // A product-declared code the shared labels do not know is shown as it is, not hidden.
      ['5', 'Account', 'import.error.shop.customer_id', 'nope'],
    ],
  )
  await unmount()
})

test('a committed run shows what was written from the run itself, and a failed one says so and offers nothing to confirm', async () => {
  const committed = run({
    id: 'run-c',
    status: 'committed',
    rows_total: 3,
    rows_valid: 3,
    committed_by: 'owner',
    finished_at: '2026-09-30T10:05:00Z',
    written: { created: 2, updated: 0, skipped: 1 },
  })
  const failed = run({ id: 'run-f', status: 'failed', rows_total: 3, rows_valid: 3, error: 'record 2: the account does not exist in this organisation' })
  const cancelled = run({ id: 'run-x', status: 'cancelled' })
  install({})
  const { container, unmount } = await mount({ initialRuns: [committed, failed, cancelled] })
  const history = all(container).find(
    (node) => node.tagName === 'TABLE' && all(node).some((cell) => cell.getAttribute?.('data-run-id') === 'run-c'),
  )
  assert.ok(history !== undefined, 'the history is drawn')
  assert.ok(all(history).some((node) => node.textContent === 'shop.customers'), 'history names the target')

  await press(container.byTestId('imports-open')[0])
  assert.equal(container.byTestId('imports-committed').length, 1)
  assert.equal(container.byTestId('imports-result-created')[0].textContent, '2')
  assert.equal(container.byTestId('imports-result-skipped')[0].textContent, '1')
  assert.equal(container.byTestId('imports-result-failed')[0].textContent, '0')
  assert.equal(container.byTestId('imports-confirm').length, 0)

  await press(container.byTestId('imports-open')[1])
  assert.equal(container.byTestId('imports-failed').length, 1)
  assert.equal(container.byTestId('imports-committed').length, 0)
  assert.equal(container.byTestId('imports-confirm').length, 0)
  assert.ok(all(container).some((node) => node.textContent === failed.error), 'the run\'s own safe sentence is shown')

  await press(container.byTestId('imports-open')[2])
  assert.equal(stateText(container), 'imports.state.cancelled')
  assert.equal(container.byTestId('imports-confirm').length, 0)
  assert.equal(buttonNamed(container, 'imports.check'), undefined)
  await unmount()
})

test('a target that declares no writer is checked but never confirmed', async () => {
  const validated = run({ status: 'validated', rows_total: 1, rows_valid: 1 })
  install({})
  const container = createContainer()
  const root = createRoot(container)
  await act(async () =>
    root.render(
      createElement(ImportPanel, {
        targets: [{ ...ACCOUNTS, committable: false, predicts: false }],
        initialRuns: [validated],
        labels,
      }),
    ),
  )
  mounted.push(() => act(async () => root.unmount()))
  await press(container.byTestId('imports-open')[0])
  assert.equal(container.byTestId('imports-confirm').length, 0)
  assert.equal(container.byTestId('imports-preview-unknown').length, 1, 'no prediction, and the page says so')
  assert.ok(all(container).some((node) => node.textContent === 'imports.notCommittable'))
})

test('with no targets the panel says so and offers nothing', async () => {
  install({})
  const container = createContainer()
  const root = createRoot(container)
  await act(async () => root.render(createElement(ImportPanel, { targets: [], initialRuns: [], labels })))
  mounted.push(() => act(async () => root.unmount()))
  assert.equal(container.byTestId('imports-panel').length, 0)
  assert.ok(all(container).some((node) => node.textContent === 'imports.noTargets'))
  assert.equal(calls.length, 0)
})

// ── The wizard: Open restores the run's real stage (GR-379) ─────────────────────────────────────

/** Storage plus a location and history the panel can write to; returns what it wrote. */
function withLocation(search = '') {
  withStorage()
  const listeners = {}
  const pushed = []
  const replaced = []
  const location = { href: 'https://app.test/dashboard/imports' + search, search }
  const move = (url) => {
    location.href = String(url)
    location.search = new URL(String(url)).search
  }
  Object.assign(globalThis.window, {
    location,
    history: {
      pushState: (_s, _t, url) => {
        pushed.push(String(url))
        move(url)
      },
      replaceState: (_s, _t, url) => {
        replaced.push(String(url))
        move(url)
      },
    },
    addEventListener: (name, listener) => {
      listeners[name] = listener
    },
    removeEventListener: () => {},
  })
  return { location, pushed, replaced, listeners, move }
}

const NEVER_WRITES = ['commitRun', 'validateRun', 'saveMapping']
const stageOfPage = (container) => container.byTestId('imports-stepper')[0].getAttribute('data-stage')
const focusedHeading = (container) =>
  focused(container)?.getAttribute?.('data-testid') === 'imports-wizard-heading'

test('Open on a run still waiting for its mapping reads its file, draws the mapping, moves focus and puts the run in the address', async () => {
  const place = withLocation()
  const created = run({ id: '11111111-1111-4111-8111-111111111111', status: 'created', columns: [] })
  const log = install({ analyseRun: async () => ({ status: 'ok', value: ANALYSIS }) })
  const { container } = await mount({ initialRuns: [created] })
  assert.equal(stageOfPage(container), 'upload', 'no run is open yet')
  await press(container.byTestId('imports-open')[0])
  await flush()
  assert.deepEqual(names(log), ['analyseRun'], 'the file is read for the mapping, and nothing is written')
  assert.equal(stageOfPage(container), 'map')
  assert.equal(container.byTestId('imports-state')[0].textContent, 'imports.state.created')
  assert.equal(all(container).filter((node) => String(node.getAttribute?.('id')).startsWith('import-map-')).length, 4)
  assert.ok(focusedHeading(container), 'focus is on the heading of what opened')
  assert.deepEqual(place.pushed, ['https://app.test/dashboard/imports?run=' + created.id])
  assert.equal(container.byTestId('imports-opened')[0].textContent, 'imports.opened')
  assert.equal(NEVER_WRITES.some((name) => names(log).includes(name)), false)
})

test('the page opened on ?run= restores that run from the server, whatever the list holds', async () => {
  withLocation('?run=22222222-2222-4222-8222-222222222222')
  const asked = run({ id: '22222222-2222-4222-8222-222222222222', status: 'created', source_name: 'from-link.xlsx' })
  const log = install({
    getRun: async () => ({ status: 'ok', value: asked }),
    analyseRun: async () => ({ status: 'ok', value: ANALYSIS }),
  })
  const { container } = await mount({ initialRuns: [], initialRunId: asked.id })
  await flush()
  assert.deepEqual(names(log), ['getRun', 'analyseRun'])
  assert.equal(stageOfPage(container), 'map')
  assert.ok(container.byTestId('imports-run-file')[0].textContent.includes('from-link.xlsx'))
})

test('a run in the address that is not this organisation\'s says so and opens nothing', async () => {
  withLocation('?run=33333333-3333-4333-8333-333333333333')
  const log = install({ getRun: async () => ({ status: 'error', message: 'errors.importRunNotFound' }) })
  const { container } = await mount({ initialRuns: [], initialRunId: '33333333-3333-4333-8333-333333333333' })
  await flush()
  assert.deepEqual(names(log), ['getRun'])
  assert.equal(stageOfPage(container), 'upload')
  assert.ok(all(container).some((node) => node.textContent === 'imports.runUnavailable'))
})

test('Open on a run whose file can no longer be read says so and offers Discard rather than a dead end', async () => {
  withLocation()
  const created = run({ id: '44444444-4444-4444-8444-444444444444', status: 'created' })
  install({ analyseRun: async () => ({ status: 'error', message: 'errors.fileNotFound' }) })
  const { container } = await mount({ initialRuns: [created] })
  await press(container.byTestId('imports-open')[0])
  await flush()
  assert.equal(all(container).filter((node) => String(node.getAttribute?.('id')).startsWith('import-map-')).length, 0)
  assert.ok(all(container).some((node) => String(node.textContent).includes('imports.fileGone')))
  assert.ok(buttonNamed(container, 'imports.discard') !== undefined)
})

test('Open on a run with problems lists them without a second click and offers the report, with no confirm', async () => {
  withLocation()
  const failed = run({
    id: '55555555-5555-4555-8555-555555555555',
    status: 'validation_failed',
    rows_total: 3,
    rows_valid: 1,
    errors_total: 2,
  })
  const log = install({
    analyseRun: async () => ({ status: 'ok', value: ANALYSIS }),
    listErrors: async () => ({
      status: 'ok',
      value: [
        { cursor: 1, row: 3, column: 'Name', field: 'name', code: 'import.error.required', value: '' },
        { cursor: 2, row: 4, column: 'Roles', field: 'roles', code: 'import.error.not_an_option', value: 'wizard' },
      ],
    }),
  })
  const { container } = await mount({ initialRuns: [failed] })
  await press(container.byTestId('imports-open')[0])
  await flush()
  assert.equal(stageOfPage(container), 'validate')
  assert.equal(container.byTestId('imports-problems').length, 1)
  assert.equal(all(container.byTestId('imports-problems')[0]).filter((node) => node.tagName === 'TR').length, 3)
  assert.equal(buttonNamed(container, 'imports.confirm'), undefined)
  assert.equal(names(log).includes('commitRun'), false)
})

test('Open on a checked run is Review: the file, the records, the policy, sample rows and the figures, and no confirm until Continue', async () => {
  withLocation()
  const validated = run({
    id: '66666666-6666-4666-8666-666666666666',
    status: 'validated',
    rows_total: 3,
    rows_valid: 3,
    mapping: { Name: 'name', Roles: 'roles' },
    predicted: { create: 2, update: 0, skip: 1 },
  })
  const queued = { ...validated, status: 'commit_requested', committed_by: 'owner' }
  const log = install({
    analyseRun: async () => ({ status: 'ok', value: ANALYSIS }),
    commitRun: async () => ({ status: 'ok', value: queued }),
    listRuns: async () => ({ status: 'ok', value: [queued] }),
  })
  const { container } = await mount({ initialRuns: [validated] })
  await press(container.byTestId('imports-open')[0])
  await flush()
  assert.equal(stageOfPage(container), 'review')
  assert.equal(container.byTestId('imports-review-file')[0].textContent, 'accounts.csv')
  assert.equal(container.byTestId('imports-review-policy')[0].textContent.length > 0, true)
  const sample = container.byTestId('imports-review-sample')[0]
  assert.ok(all(sample).some((node) => node.tagName === 'TD' && node.textContent === 'Acme Ltd'))
  assert.equal(container.byTestId('imports-preview-create')[0].textContent, 'imports.preview.create2')
  assert.equal(container.byTestId('imports-confirm').length, 0, 'Review is not Confirm')
  assert.equal(buttonNamed(container, 'imports.confirm'), undefined)
  assert.equal(container.byTestId('imports-state')[0].textContent, 'imports.state.validated')

  await press(buttonNamed(container, 'imports.review.continue'))
  assert.equal(stageOfPage(container), 'confirm')
  assert.equal(container.byTestId('imports-state')[0].textContent, 'imports.state.awaitingConfirmation')
  assert.equal(names(log).includes('commitRun'), false, 'reaching Confirm commits nothing')
  await press(buttonNamed(container, 'imports.review.back'))
  assert.equal(stageOfPage(container), 'review')
  await press(buttonNamed(container, 'imports.review.continue'))

  await press(buttonNamed(container, 'imports.confirm'))
  assert.deepEqual(names(log).filter((n) => n === 'commitRun'), ['commitRun'], 'one click, one commit')
  assert.equal(stageOfPage(container), 'processing')
})

test('Review can go back to the mapping and the person can change it', async () => {
  withLocation()
  const validated = run({ id: '77777777-7777-4777-8777-777777777777', status: 'validated', rows_total: 1, rows_valid: 1, predicted: { create: 1, update: 0, skip: 0 } })
  install({ analyseRun: async () => ({ status: 'ok', value: ANALYSIS }) })
  const { container } = await mount({ initialRuns: [validated] })
  await press(container.byTestId('imports-open')[0])
  await flush()
  assert.equal(all(container).filter((node) => String(node.getAttribute?.('id')).startsWith('import-map-')).length, 0)
  await press(buttonNamed(container, 'imports.review.changeMapping'))
  assert.equal(stageOfPage(container), 'map')
  assert.equal(all(container).filter((node) => String(node.getAttribute?.('id')).startsWith('import-map-')).length, 4)
})

test('Open on a run being written is Processing: persisted state, a way to come back, no confirm, nothing invented', async () => {
  withLocation()
  for (const status of ['commit_requested', 'committing']) {
    const writing = run({ id: '88888888-8888-4888-8888-888888888888', status, committed_by: 'owner', rows_total: 3, rows_valid: 3 })
    const log = install({ listRuns: async () => ({ status: 'ok', value: [writing] }) })
    const { container } = await mount({ initialRuns: [writing] })
    await press(container.byTestId('imports-open')[0])
    await flush(5)
    assert.equal(stageOfPage(container), 'processing', status)
    assert.equal(container.byTestId('imports-processing').length, 1)
    assert.equal(buttonNamed(container, 'imports.confirm'), undefined)
    assert.equal(names(log).includes('analyseRun'), false, 'a run being written is not re-read for a mapping')
    assert.equal(container.byTestId('imports-committed').length, 0, 'nothing claims success while it is running')
    assert.equal(/\d\s?%/.test(container.textContent), false, 'no invented percentage')
    await mounted.pop()?.()
  }
})

test('Open on a completed run is Results: the counts, a link to the records, and Import another file', async () => {
  const place = withLocation()
  const done = run({
    id: '99999999-9999-4999-8999-999999999999',
    status: 'committed',
    committed_by: 'owner',
    rows_total: 3,
    rows_valid: 3,
    written: { created: 2, updated: 0, skipped: 1 },
  })
  const log = install({})
  const { container } = await mount({
    initialRuns: [done],
    recordLinks: { 'shop.customers': { href: '/dashboard/accounts', label: 'View the accounts' } },
  })
  await press(container.byTestId('imports-open')[0])
  await flush(5)
  assert.equal(stageOfPage(container), 'results')
  assert.equal(container.byTestId('imports-result-created')[0].textContent, '2')
  assert.equal(container.byTestId('imports-result-skipped')[0].textContent, '1')
  const link = all(container).find((node) => node.tagName === 'A' && node.getAttribute('href') === '/dashboard/accounts')
  assert.ok(link !== undefined, 'a link to the imported records')
  assert.deepEqual(names(log), [], 'a finished run needs no further reads')
  await press(buttonNamed(container, 'imports.anotherFile'))
  assert.equal(stageOfPage(container), 'upload')
  assert.equal(container.byTestId('imports-state').length, 0)
  assert.equal(place.pushed.at(-1), 'https://app.test/dashboard/imports', 'the run leaves the address')
  assert.equal(focused(container), byId(container, 'import-file'))
})

test('Open on a cancelled run explains it, marks no step current and offers Import another file', async () => {
  withLocation()
  const stopped = run({ id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', status: 'cancelled' })
  install({})
  const { container } = await mount({ initialRuns: [stopped] })
  await press(container.byTestId('imports-open')[0])
  await flush(5)
  assert.equal(stageOfPage(container), 'ended')
  assert.ok(all(container).some((node) => node.textContent === 'imports.cancelledNote'))
  assert.ok(buttonNamed(container, 'imports.anotherFile') !== undefined)
})

test('Back and Forward move between runs and out of them, reading the run from the server', async () => {
  const place = withLocation()
  const one = run({ id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', status: 'created' })
  const log = install({
    getRun: async () => ({ status: 'ok', value: one }),
    analyseRun: async () => ({ status: 'ok', value: ANALYSIS }),
  })
  const { container } = await mount({ initialRuns: [one] })
  await press(container.byTestId('imports-open')[0])
  await flush(5)
  assert.equal(stageOfPage(container), 'map')
  place.move('https://app.test/dashboard/imports')
  await act(async () => place.listeners.popstate())
  await flush(5)
  assert.equal(stageOfPage(container), 'upload', 'Back to the bare page leaves the run')
  place.move('https://app.test/dashboard/imports?run=' + one.id)
  await act(async () => place.listeners.popstate())
  await flush(10)
  assert.equal(stageOfPage(container), 'map', 'Forward returns to it')
  assert.ok(names(log).includes('getRun'))
})

test('nothing is written by opening, refreshing or polling: no mapping, check or commit without a click', async () => {
  withLocation('?run=cccccccc-cccc-4ccc-8ccc-cccccccccccc')
  const validated = run({ id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', status: 'validated', rows_total: 1, rows_valid: 1, predicted: { create: 1, update: 0, skip: 0 } })
  const log = install({
    getRun: async () => ({ status: 'ok', value: validated }),
    analyseRun: async () => ({ status: 'ok', value: ANALYSIS }),
    listRuns: async () => ({ status: 'ok', value: [validated] }),
  })
  await mount({ initialRuns: [validated], initialRunId: validated.id })
  await flush(30)
  for (const name of NEVER_WRITES) assert.equal(names(log).includes(name), false, name)
})

test('Recent imports shows the file and a date on the reader\'s clock, with the stored instant kept', async () => {
  withLocation()
  const row = run({ id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', created_at: '2026-10-08T13:55:17.448663Z', source_name: 'my-accounts.xlsx' })
  install({})
  const { container } = await mount({ initialRuns: [row] })
  await flush(3)
  const history = container.byTestId('imports-history')[0]
  assert.ok(all(history).some((node) => node.tagName === 'TD' && node.textContent === 'my-accounts.xlsx'))
  const time = all(history).find((node) => node.tagName === 'TIME')
  assert.equal(time.getAttribute('datetime'), '2026-10-08T13:55:17.448663Z')
  assert.equal(time.textContent.includes('T13:55:17'), false, 'not the raw ISO string')
})

