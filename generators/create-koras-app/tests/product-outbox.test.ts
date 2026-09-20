import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import yaml from 'js-yaml'
import { templatePath } from './template-path'

/**
 * The notification outbox, checked from the template text.
 *
 * CAT-01 Phase 3, 2026-09-20. Phase 2 gave notification one place to leave
 * from and handed the prepared mail back to the caller, which handed it to a
 * FastAPI background task — the arrangement PLAT-F1 exists to replace, because
 * such a task runs in the API process and is lost when it restarts. A deploy
 * during a send lost the send, and a mail server refusing connections for ten
 * minutes lost every notification raised in those ten minutes, with nothing
 * anywhere saying so.
 *
 * The properties below are the ones that make the exit criterion true and
 * would be easy to undo without any test noticing.
 */

const PRODUCT = join(templatePath('product', 'package.json.hbs'), '..')
const PROFILE = join(PRODUCT, '..')

function read(...segments: string[]): string {
  return readFileSync(join(PRODUCT, ...segments), 'utf8').split(String.fromCharCode(13)).join('')
}

function has(...segments: string[]): boolean {
  return existsSync(join(PRODUCT, ...segments))
}

describe('the notification outbox', () => {
  const store = read('services/api/koras_api/core/outbox.py')
  const sweep = read('services/worker/koras_worker/tasks/outbox.py')
  const seam = read('services/api/koras_api/core/dispatch.py')
  const migration = read('supabase/migrations/00037_notification_outbox.sql')

  it('ships inside the capability that owns it', () => {
    const manifest = yaml.load(readFileSync(join(PROFILE, 'manifest.yaml'), 'utf8')) as {
      template_map: { capabilities: Record<string, string | string[]> }
    }
    const entry = manifest.template_map.capabilities.notifications
    const paths = typeof entry === 'string' ? [entry] : entry
    for (const expected of [
      'supabase/migrations/00037_notification_outbox.sql',
      'services/api/koras_api/core/outbox.py',
      'services/worker/koras_worker/tasks/outbox.py',
      'supabase/tests/300_notification_outbox_isolation.sql',
      'tests/unit/test_outbox.py',
    ]) {
      expect(paths).toContain(expected)
      expect(has(expected) || has(`${expected}.hbs`), `${expected} is gated but absent`).toBe(true)
    }
  })

  it('no longer sends from the request', () => {
    // The whole change. `dispatch.send` is gone and the route queues nothing.
    expect(seam).not.toContain('async def send(')
    expect(seam).toContain('await outbox.enqueue(')
    const route = read('services/api/koras_api/routers/ai.py')
    expect(route).not.toContain('send_notifications')
    expect(route, 'the route sends from a background task again').not.toMatch(
      /background\.add_task\([^)]*mail/,
    )
  })

  it('writes the row on the caller-s own session', () => {
    // So it commits or rolls back with the thing that caused it. A row written
    // on another session would be a message owed for something that never
    // happened.
    const body = seam.slice(seam.indexOf('async def dispatch('), seam.indexOf('def _renderer('))
    expect(body).toContain('outbox.enqueue(\n            session,')
  })

  it('stores the words rather than the means to rebuild them', () => {
    // A retry an hour later against state that has changed would otherwise
    // send a different message from the one that was decided.
    for (const column of ['subject', 'body_text', 'body_html', 'locale']) {
      expect(migration).toContain(column)
    }
    expect(store).toContain('"body_html": body_html')
  })

  it('cannot send one message twice', () => {
    // The sweep runs every minute; a send that overruns its minute is two runs
    // at once, and without this the same person gets the same mail twice.
    expect(store).toContain('for update skip locked')
    // And the attempt is counted on the claim, so a worker that dies mid-send
    // leaves a message that knows it was tried.
    expect(store).toContain('attempts = attempts + 1')
  })

  it('gives up visibly rather than silently', () => {
    // The difference from the log line this replaces: somebody can find it.
    expect(store).toContain('MAX_ATTEMPTS')
    expect(store).toContain('"abandoned" if give_up else "pending"')
    expect(migration).toContain('notification_outbox_abandoned_has_a_reason')
    // And a message that claims to have been sent names when.
    expect(migration).toContain('notification_outbox_sent_has_a_time')
  })

  it('keeps the provider-s own message id', () => {
    // NOTIF-GAP-005. `koras_email.Sent` has carried it since it was written
    // and every call site discarded it; it is the only handle connecting a row
    // here to a line in a mail provider's own log.
    expect(migration).toContain('message_id')
    expect(sweep).toContain('message_id=outcome.message_id')
    // And a recorded send is distinguishable from a delivered one.
    expect(sweep).toContain('simulated=outcome.simulated')
  })

  it('lets nobody read a colleague-s mail', () => {
    // The table holds the rendered body of every notification, including ones
    // addressed to somebody else, so there is no tenant select policy at all —
    // a stronger claim than cross-tenant isolation, and one that would be easy
    // to weaken later "for a status page".
    expect(migration).toContain('for insert')
    expect(migration).not.toMatch(/for select\s*\n\s*using \(tenant_id = public\.current_tenant_id/)
    expect(migration).toContain('public.is_provisioning()')
    const suite = read('supabase/tests/300_notification_outbox_isolation.sql')
    expect(suite).toContain('a customer read')
  })

  it('runs often enough to be a notification', () => {
    // A nightly sweep would make "you have an action to approve" arrive the
    // following morning.
    const worker = read('services/worker/koras_worker/worker.py.hbs')
    expect(worker).toContain('cron(send_owed_notifications, second=0)')
  })

  it('is carried into the worker image', () => {
    // Reached by `importlib`, so a missing file is a skipped sweep rather than
    // a crash — which makes forgetting the COPY invisible without this.
    const dockerfile = readFileSync(
      join(PROFILE, '..', '_shared', 'template', 'services', 'worker', 'Dockerfile.hbs'),
      'utf8',
    )
    expect(dockerfile).toContain('koras_api/core/outbox.py')
    expect(sweep).toContain("importlib.import_module(\"koras_api.core.outbox\")")
  })
})
