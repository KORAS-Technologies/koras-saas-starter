import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import yaml from 'js-yaml'
import { templatePath } from './template-path'

/**
 * The notification dispatch point, checked from the template text.
 *
 * CAT-01 Phase 2, 2026-09-19. Phase 1 gave a product a feed; this gave it one
 * place a notification leaves from, so that the second producer does not copy
 * what the first one did.
 *
 * The properties worth a structural test are the ones a passing unit test can
 * still hide, because they are about *where* code is rather than what it does.
 *
 * **No producer composes or sends.** The assistant's approval notice used to
 * resolve its own audience twice, build its own HTML and drive its own sender
 * loop. If a route regains any of that, the seam is a seam in name only.
 *
 * **The feed is written on the caller's session and mail is not sent on it.**
 * ADR 0008 rule 2. A row can be rolled back and a mail cannot, so `dispatch`
 * hands the mail back and the route sends it after its commit.
 *
 * **A preference is read through the resolver.** Not from a row. The whole
 * reason `notifications.emailEnabled` could be switched off while mail kept
 * arriving is that nothing read it at all.
 */

const PRODUCT = join(templatePath('product', 'package.json.hbs'), '..')
const PROFILE = join(PRODUCT, '..')

function read(...segments: string[]): string {
  return readFileSync(join(PRODUCT, ...segments), 'utf8').split(String.fromCharCode(13)).join('')
}

function has(...segments: string[]): boolean {
  return existsSync(join(PRODUCT, ...segments))
}

describe('the notification dispatch point', () => {
  it('exists in the foundation, gated by nothing', () => {
    // Every product has a feed and a way to send to it. `notifications` gates
    // the table and the surface; the seam above them is foundation, the way
    // the audit registry is.
    expect(has('services/api/koras_api/core/dispatch.py')).toBe(true)
    expect(has('services/api/koras_api/core/recipients.py')).toBe(true)

    const manifest = yaml.load(readFileSync(join(PROFILE, 'manifest.yaml'), 'utf8')) as {
      template_map: { capabilities: Record<string, string | string[]> }
    }
    for (const entry of Object.values(manifest.template_map.capabilities)) {
      const paths = typeof entry === 'string' ? [entry] : entry
      for (const path of paths) {
        expect(path, 'the dispatch seam is inside a capability gate').not.toContain(
          'core/dispatch.py',
        )
        expect(path).not.toContain('core/recipients.py')
      }
    }
  })

  it('leaves no producer composing or sending for itself', () => {
    const route = read('services/api/koras_api/routers/ai.py')
    expect(route).toContain('await dispatch(')
    // The three things it used to do and must not do again.
    expect(route, 'a route resolves its own audience').not.toContain('notify.approvers(')
    expect(route, 'a route writes its own feed row').not.toContain('announce_awaiting_approval')
    expect(route, 'a route drives its own sender loop').not.toContain('notify_awaiting_approval')
  })

  it('sends the mail after the commit and never on the session', () => {
    const route = read('services/api/koras_api/routers/ai.py')
    const commit = route.indexOf('await ai.session.commit()')
    const send = route.indexOf('background.add_task(send_notifications')
    expect(commit).toBeGreaterThan(-1)
    expect(send).toBeGreaterThan(-1)
    expect(send, 'the mail is queued before the commit').toBeGreaterThan(commit)

    // And `dispatch` itself prepares rather than sends: nothing in it awaits a
    // sender. `send` is a separate function the caller reaches for.
    const seam = read('services/api/koras_api/core/dispatch.py')
    const dispatchBody = seam.slice(
      seam.indexOf('async def dispatch('),
      seam.indexOf('async def _to_feed('),
    )
    expect(dispatchBody).not.toContain('sender')
  })

  it('reads a preference through the resolver rather than from a row', () => {
    const seam = read('services/api/koras_api/core/dispatch.py')
    expect(seam).toContain('resolve_setting(')
    expect(seam).toContain('catalogue.require(key)')
    // Both scopes fed in, so the ladder the settings page shows is the ladder
    // the send applies.
    expect(seam).toContain('global_values=')
    expect(seam).toContain('organization_values=')
    expect(seam).toContain('member_values=')
    // No hand-written SQL against the settings tables anywhere in the seam.
    expect(seam).not.toContain('setting_values')
  })

  it('honours the two channels separately', () => {
    const seam = read('services/api/koras_api/core/dispatch.py')
    expect(seam).toContain("IN_APP_SETTING = 'notifications.inAppEnabled'".replace(/'/g, '"'))
    expect(seam).toContain("EMAIL_SETTING = 'notifications.emailEnabled'".replace(/'/g, '"'))
    // Turning one off must not turn the other off: each channel reads its own.
    const feed = seam.slice(seam.indexOf('async def _to_feed('), seam.indexOf('async def _to_mail('))
    const mail = seam.slice(seam.indexOf('async def _to_mail('), seam.indexOf('async def send('))
    expect(feed).toContain('wants(IN_APP_SETTING,')
    expect(feed).not.toContain('EMAIL_SETTING')
    expect(mail).toContain('wants(EMAIL_SETTING,')
    expect(mail).not.toContain('IN_APP_SETTING')
  })

  it('offers the email preference only at a level something can read', () => {
    // A mail goes to an address; the platform's member list carries an email
    // and a role and no subject, so a person-level switch on this setting
    // could never be read. Narrowed to the organisation rather than hidden --
    // hiding an unreadable control is the same mistake in a different place.
    const standard = read('services/api/koras_api/settings_catalogue/standard.py')
    const entry = standard.slice(standard.indexOf('"notifications.emailEnabled"'))
    const body = entry.slice(0, entry.indexOf('\n    ),'))
    expect(body).toContain('Scope.GLOBAL_ORG,')
    expect(body).not.toContain('Scope.GLOBAL_ORG_USER')
    // And it is offered again: it was hidden while nothing honoured it.
    expect(body).not.toMatch(/^\s+surfaced=False/m)
  })

  it('declares the audience once, as data rather than a query', () => {
    const notify = read('services/api/koras_api/core/notify.py')
    expect(notify).toContain('APPROVAL_AUDIENCE = Audience(')
    // The permission was written into two functions, so a second producer
    // would have copied both.
    expect(notify).not.toContain('async def approvers(')
    expect(notify).not.toContain('async def approver_subjects(')
    const audience = read('services/api/koras_api/core/recipients.py')
    expect(audience).toContain('class Audience:')
    // A rule that is data can be logged and compared; a lambda can only be run.
    expect(audience).toContain('@dataclass(frozen=True)\nclass Audience:')
  })

  it('renders once per language, not once per person', () => {
    const seam = read('services/api/koras_api/core/dispatch.py')
    const feed = seam.slice(seam.indexOf('async def _to_feed('), seam.indexOf('async def _to_mail('))
    // Grouped by locale before rendering, so two people who share a language
    // provably see the same words.
    expect(feed).toContain('wanted: dict[Locale, list[str]]')
    expect(feed).toContain('for locale, subjects in sorted(wanted.items())')
  })

  it('resolves a recipient-s language from their own settings, not the request', () => {
    const audience = read('services/api/koras_api/core/recipients.py')
    expect(audience).toContain('member_values(session, tenant_id, subject)')
    expect(audience).toContain("values.get('general.language')".replace(/'/g, '"'))
    // The request's language is a fallback now and nothing more.
    const route = read('services/api/koras_api/routers/ai.py')
    expect(route).toContain('fallback_locale=resolve_locale(locale)')
  })

  it('reads each scope once rather than once per person per channel', () => {
    // DISP-01. `_enabled` was a function that read all three scopes on every
    // call, and it is called once per person per channel: eleven reads each of
    // the platform's defaults and the organisation's values for ten approvers,
    // on the request path.
    const seam = read('services/api/koras_api/core/dispatch.py')
    expect(seam).toContain('class Preferences:')
    // Nothing outside the reader touches the stores directly any more.
    const outside = seam.slice(seam.indexOf('async def dispatch('))
    expect(outside).not.toContain('await global_values(')
    expect(outside).not.toContain('await tenant_values(')
    expect(outside).not.toContain('await member_values(')
    // And the resolver shares the reader's cache rather than keeping its own.
    expect(seam).toContain('read_member=wants.member_values')
    const audience = read('services/api/koras_api/core/recipients.py')
    expect(audience).toContain('read_member: MemberReader | None = None')
  })

  it('fails open on the feed and closed on the mail', () => {
    // DISP-03. A mail sent to somebody who switched mail off cannot be
    // recalled; a mail withheld costs them nothing, because the feed row
    // exists either way.
    const seam = read('services/api/koras_api/core/dispatch.py')
    expect(seam).toContain('wants(IN_APP_SETTING, person.subject, when_unknown=True)')
    expect(seam).toContain('wants(EMAIL_SETTING, person.subject, when_unknown=False)')
  })

  it('renders once per language in both channels, not once per person', () => {
    // DISP-02. The inbox half called the template per recipient, and the test
    // that claimed otherwise used a case with no addresses in it.
    const seam = read('services/api/koras_api/core/dispatch.py')
    expect(seam).toContain('def _renderer(')
    const mail = seam.slice(seam.indexOf('async def _to_mail('), seam.indexOf('async def send('))
    expect(mail, 'the inbox half renders for itself').not.toContain('event.render(')
    const feed = seam.slice(seam.indexOf('async def _to_feed('), seam.indexOf('async def _to_mail('))
    expect(feed).not.toContain('event.render(')
  })

  it('ships its own suite', () => {
    expect(has('tests/unit/test_dispatch.py')).toBe(true)
    const suite = read('tests/unit/test_dispatch.py')
    // The exit criterion for this phase, as a test with that name.
    expect(suite).toContain(
      'test_switching_off_notification_emails_switches_off_notification_emails',
    )
    expect(suite).toContain('test_one_persons_preference_does_not_silence_another')
    expect(suite).toContain('test_mail_is_returned_rather_than_sent')
    // The cost, asserted as a count: the defect was invisible to every
    // assertion about what was decided.
    expect(suite).toContain('test_the_shared_scopes_are_read_once_however_many_recipients')
  })
})
