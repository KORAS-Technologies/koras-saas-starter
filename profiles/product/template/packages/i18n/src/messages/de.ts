import type { en } from './en.js'

/**
 * German.
 *
 * Typed against the English catalogue, so a key missing here or present only
 * here is a compile error rather than a gap somebody finds on a screen. Formal
 * address throughout ("Sie"), because this is a product a company rolls out to
 * its staff rather than an app a person downloads for themselves, and a
 * catalogue that mixed the two would read as two products.
 *
 * Placeholders and inline tags are the same vocabulary as `en.ts` and must be
 * carried over: a translation that drops `{product}` renders a sentence with a
 * hole in it, and one that drops `<code>` renders the markup as text.
 */
export const de: Readonly<Record<keyof typeof en, string>> = {
  /* ---------------------------------------------------------------- common */
  'common.skipToMain': 'Zum Inhalt springen',
  'common.signIn': 'Anmelden',
  'common.getStarted': 'Loslegen',
  'common.goToDashboard': 'Zum Dashboard',
  'common.none': 'Keine',
  'common.language': 'Sprache',
  'common.copyright': '© {year} {product}',

  /* --------------------------------------------------- authenticated shell */
  'shell.openNavigation': 'Navigation öffnen',
  'shell.closeNavigation': 'Navigation schließen',
  'shell.expandSidebar': 'Seitenleiste ausklappen',
  'shell.collapseSidebar': 'Seitenleiste einklappen',
  'shell.productNavigation': 'Produktnavigation',
  'shell.navigationLabel': 'Produkt',
  'shell.drawerNavigationLabel': 'Produkt, Menü',
  'shell.workspace': 'Arbeitsbereich: ',
  'shell.accountMenu': 'Kontomenü',
  'shell.signedIn': 'Angemeldet',
  'shell.manageSubscription': 'Abonnement verwalten',
  'shell.opensPortal': '(öffnet das Koras-Kundenportal)',
  'shell.signOut': 'Abmelden',
  'shell.appearance': 'Darstellung',
  'shell.themeLight': 'Hell',
  'shell.themeSystem': 'System',
  'shell.themeDark': 'Dunkel',
  'shell.lockedPlan': 'Nicht in Ihrem Tarif enthalten',
  'shell.lockedFeature': 'Für Ihre Organisation nicht aktiviert',
  'shell.roleAdministrator': 'Administrator',
  'shell.roleMember': 'Mitglied',

  'accessDenied.title': 'Sie haben keinen Zugriff auf diese Seite',
  'accessDenied.description':
    'Sie sind angemeldet, aber Ihr Konto hat keine Berechtigung für diesen Bereich. Ein Administrator Ihrer Organisation kann das ändern.',

  /* ------------------------------------------------------- public header */
  'header.primary': 'Hauptnavigation',
  'header.primarySmall': 'Hauptnavigation, kleiner Bildschirm',
  'header.openMenu': 'Menü öffnen',
  'header.closeMenu': 'Menü schließen',
  'footer.builtBy': 'Entwickelt von',
  'footer.on': '{product} auf {network}',

  /* ------------------------------------------------- the drawn app frame */
  'appFrame.workspace': 'Arbeitsbereich',
  'appFrame.overview': 'Betriebsübersicht',
  'appFrame.open': 'Offen',
  'appFrame.dueToday': 'Heute fällig',
  'appFrame.blocked': 'Blockiert',
  'appFrame.inProgress': 'In Arbeit',
  'appFrame.waiting': 'Wartend',
  'appFrame.scheduled': 'Geplant',
  'appFrame.row.onboarding': 'Onboarding · Northwind',
  'appFrame.row.renewal': 'Verlängerungsprüfung · Contoso',
  'appFrame.row.access': 'Zugriffsanfrage · Fabrikam',
  'appFrame.row.export': 'Quartalsexport',

  /* -------------------------------------------------------------- sign-in */
  'login.title': 'Anmelden',
  'login.heading': 'Bei {product} anmelden',
  'login.description':
    'Sie werden zur Anmeldung Ihrer Organisation weitergeleitet und danach direkt zurückgebracht.',
  'login.noAccount': 'Noch kein Konto?',
  'login.note':
    'Die Anmeldung erfolgt über Ihr Organisationskonto. Es gibt kein separates {product}-Passwort, das Sie sich merken oder zurücksetzen müssten.',

  /* --------------------------------------------------------------- signup */
  'signup.title': 'Loslegen',
  'signup.heading': 'Mit {product} starten',
  'signup.description':
    'Sagen Sie uns, wohin wir Ihren Bestätigungslink schicken sollen. Es wird nichts angelegt, bevor Sie ihn öffnen.',
  'signup.haveAccount': 'Sie haben bereits ein Konto?',
  'signup.form.organisation': 'Organisation',
  'signup.form.email': 'Geschäftliche E-Mail-Adresse',
  'signup.form.name': 'Ihr Name',
  'signup.form.optional': 'Optional.',
  'signup.form.plan': 'Tarif',
  'signup.form.submit': 'Konto erstellen',
  'signup.form.submitting': 'Ihr Konto wird erstellt',
  'signup.form.note':
    'Wir schicken Ihnen einen Link zur Bestätigung der Adresse. Es wird nichts angelegt, bevor Sie ihn öffnen.',
  'signup.sent.title': 'Prüfen Sie Ihr E-Mail-Postfach',
  'signup.sent.message':
    'In {email} finden Sie einen Link zur Bestätigung Ihrer Adresse. Es wird nichts angelegt, bevor Sie ihn öffnen.',
  'signup.error.tooMany': 'Zu viele Versuche von hier. Bitte versuchen Sie es in Kürze erneut.',
  'signup.error.planUnavailable':
    'Dieser Tarif kann nicht online abgeschlossen werden. Bitte kontaktieren Sie uns.',
  'signup.error.checkDetails': 'Prüfen Sie Ihre Angaben und versuchen Sie es erneut.',
  'signup.error.generic': 'Etwas ist schiefgelaufen. Bitte versuchen Sie es erneut.',
  'signup.error.email': 'Geben Sie Ihre E-Mail-Adresse ein.',
  'signup.error.organisation': 'Wie heißt Ihre Organisation?',
  'signup.error.notAvailable': 'Die Registrierung ist derzeit nicht verfügbar.',
  'signup.error.notConfigured':
    'Die Registrierung ist noch nicht verfügbar. Bitte kontaktieren Sie uns.',
  'signup.error.unreachable': 'Der Registrierungsdienst war nicht erreichbar.',

  'requestAccess.heading': 'Mit {product} loslegen',
  'requestAccess.byAdmin':
    'Der Zugang zu {product} wird vom Administrator Ihrer Organisation eingerichtet, nicht online. Wenn Sie der Administrator sind, wenden Sie sich an die Stelle, die {product} für Ihre Organisation betreibt.',
  'requestAccess.withContact':
    'Konten für {product} richten wir gemeinsam mit Ihnen ein. Erzählen Sie uns kurz etwas über Ihre Organisation, und wir bringen Sie an den Start.',
  'requestAccess.button': 'Zugang anfragen',
  'requestAccess.subject': 'Zugang zu {product}',

  'invitation.heading': '{product} ist nur auf Einladung zugänglich',
  'invitation.description':
    'Neue Organisationen kommen auf Einladung zu {product}. Wenn Sie eingeladen wurden, ist der Link in Ihrer E-Mail der Weg hinein — diese Seite kann das Konto nicht für Sie anlegen.',
  'invitation.ask': 'Nach einer Einladung fragen',
  'invitation.byAdmin': 'Einladungen werden vom Administrator Ihrer Organisation ausgesprochen.',
  'invitation.subject': 'Einladung zu {product}',

  'verify.title': 'E-Mail-Adresse bestätigen',
  'verify.incomplete.title': 'Dieser Link ist unvollständig',
  'verify.incomplete.description':
    'Öffnen Sie den Link aus Ihrer E-Mail erneut oder beginnen Sie von vorn.',
  'verify.incomplete.startOver': 'Von vorn beginnen',
  'verify.rateLimited.title': 'Zu viele Versuche',
  'verify.rateLimited.description':
    'Ihr Link ist weiterhin gültig. Warten Sie einige Minuten und öffnen Sie ihn erneut — beginnen Sie nicht von vorn, das hilft nicht.',
  'verify.invalid.title': 'Dieser Link ist ungültig',
  'verify.invalid.description':
    'Er wurde möglicherweise bereits verwendet oder ist abgelaufen. Registrieren Sie sich erneut, um einen neuen zu erhalten.',
  'verify.invalid.again': 'Erneut registrieren',

  'provisioning.ready.title': 'Ihr Arbeitsbereich ist bereit',
  'provisioning.ready.description': 'Sie werden zur Anmeldung bei {product} weitergeleitet.',
  'provisioning.ready.redirecting': 'Weiterleitung…',
  'provisioning.ready.continue': 'Weiter zur Anmeldung',
  'provisioning.failed.title': 'Wir konnten die Einrichtung Ihres Arbeitsbereichs nicht abschließen',
  'provisioning.failed.description':
    'Ihre E-Mail-Adresse ist bestätigt, und nichts ist verloren. Jemand muss sich das ansehen, bevor Sie sich anmelden können.',
  'provisioning.failed.descriptionContact':
    'Ihre E-Mail-Adresse ist bestätigt, und nichts ist verloren. Jemand muss sich das ansehen, bevor Sie sich anmelden können — und wir würden gern von Ihnen hören.',
  'provisioning.failed.getInTouch': 'Kontakt aufnehmen',
  'provisioning.failed.subject': 'Einrichtung von {product}',
  'provisioning.slow.title': 'Das dauert länger als üblich',
  'provisioning.slow.description':
    'Ihr Konto wird noch eingerichtet. Wir schreiben Ihnen, sobald es bereit ist — Sie können diese Seite schließen.',
  'provisioning.waiting.title': 'Ihr Arbeitsbereich wird eingerichtet',
  'provisioning.waiting.description':
    'Wir legen <strong>{slug}</strong> in {product} an. Das dauert in der Regel ein bis zwei Minuten.',
  'provisioning.waiting.descriptionNoSlug':
    'Wir legen Ihren Arbeitsbereich in {product} an. Das dauert in der Regel ein bis zwei Minuten.',
  'provisioning.waiting.status':
    'Ihre Organisation, Ihr Konto und Ihr Arbeitsbereich werden eingerichtet.',
  'provisioning.waiting.close':
    'Sie können diese Seite schließen — wir schreiben Ihnen, sobald alles bereit ist.',

  'notFound.title': 'Diese Seite können wir nicht finden',
  'notFound.description': 'Der Link ist möglicherweise veraltet, oder die Seite wurde verschoben.',
  'notFound.home': 'Zur Startseite',

  /* ------------------------------------------------------------ dashboard */
  'dashboard.welcome': 'Willkommen bei {product}',
  'dashboard.intro':
    'Sie sind angemeldet. Dies ist der Ausgangspunkt für {product}; der erste Bildschirm, den Ihr Team baut, ersetzt diesen.',
  'dashboard.start.title': 'Wo Sie anfangen',
  'dashboard.start.build':
    'Bauen Sie diese Seite in <code>apps/web/src/app/dashboard</code>. Alles, was Sie daneben anlegen, ist standardmäßig geschützt, sitzt in der Produkt-Shell und übernimmt das Branding dieses Kunden.',
  'dashboard.start.sidebar':
    'Geben Sie einem neuen Bereich einen Platz in der Seitenleiste, indem Sie ein Modul zu <code>navigation</code> in <code>packages/branding/src/index.ts</code> hinzufügen. An der Shell ändert sich nichts; derselbe Eintrag schützt auch die Route.',
  'dashboard.start.config':
    'Die öffentliche Website, ihre Inhalte, die Farben dieses Produkts und die angebotenen Sprachen werden in derselben Datei konfiguriert.',
  'dashboard.start.branding':
    'Die Farben eines Kunden kommen über <code>apps/web/src/lib/tenant-branding.ts</code>, gelesen aus dem, was er im Portal der Plattform festgelegt hat, und über die Mandanteneinstellungen dieses Produkts gelegt.',

  'insights.title': 'Einblicke',
  'insights.notInPlan':
    'Einblicke sind nicht Teil Ihres Tarifs. Sprechen Sie uns an, wenn Sie sie hinzufügen möchten.',

  'reports.title': 'Berichte',
  'reports.notIncluded.title': 'Nicht in Ihrem Tarif enthalten',
  'reports.notIncluded.description':
    'Erweiterte Berichte gehören zu einem höheren Tarif. Ihr aktueller Tarif ist <strong>{plan}</strong>.',
  'reports.notIncluded.notRecorded': 'nicht erfasst',
  'reports.unresolved':
    'Ihr Tarif konnte gerade nicht von der KORAS-Plattform gelesen werden; möglicherweise steht Ihnen dies also zur Verfügung. Der Grund steht im Serverprotokoll dieser Installation.',
  'reports.included':
    'In Ihrem Tarif enthalten. Bauen Sie hier das Eigentliche — diese Seite existiert, damit die Tarifprüfung irgendwohin führt und das Muster sichtbar ist, bevor jemand es braucht.',

  /* ------------------------------------------------------------- settings */
  'settings.title': 'Einstellungen',
  'settings.intro':
    'Was {product} ist, was diese Installation enthält und was der Tarif Ihrer Organisation umfasst.',
  'settings.product.title': 'Produkt',
  'settings.product.name': 'Name',
  'settings.product.identifier': 'Kennung',
  'settings.product.tagline': 'Leitsatz',
  'settings.product.configuredIn':
    'Konfiguriert in <code>packages/branding/src/index.ts</code>, wo auch die Farben, das Logo, die Sprachen und die Seitenleistenmodule dieses Produkts festgelegt sind.',
  'settings.deployment.title': 'Diese Installation',
  'settings.deployment.description':
    'Die Komponenten, mit denen dieses Repository erzeugt wurde. Ein Seitenleistenmodul, das eine fehlende Komponente voraussetzt, wird ausgeblendet statt zu brechen, und die Liste steht für die Lebensdauer des Repositorys fest — eine Komponente hinzuzufügen heißt, mit ihr zu generieren.',
  'settings.plan.title': 'Tarif',
  'settings.plan.resolved': 'Von der KORAS-Plattform für Ihre Organisation ermittelt.',
  'settings.plan.plan': 'Tarif',
  'settings.plan.features': 'Enthaltene Funktionen',
  'settings.plan.noneRecorded': 'Keiner erfasst',
  'settings.plan.unavailable':
    'Nicht verfügbar. Ihr Tarif konnte gerade nicht von der KORAS-Plattform gelesen werden, daher ist alles Tarifgebundene bis dahin nicht verfügbar. Alles andere am Produkt ist davon unberührt; der Grund steht im Serverprotokoll dieser Installation.',
  'settings.plan.portalHint':
    'Abonnements und Abrechnung werden im KORAS-Kundenportal verwaltet. Setzen Sie <code>product.accountUrl</code>, um von hier und aus dem Profilmenü darauf zu verlinken.',
  'settings.plan.manage': '<a>Abonnement verwalten</a> im KORAS-Kundenportal.',
  'settings.language.title': 'Sprache',
  'settings.language.description':
    'Die Sprache, in der {product} Ihnen auf diesem Gerät angezeigt wird. Sie gilt nur für die Oberfläche; was Ihre Organisation in das Produkt einträgt, bleibt so, wie es eingegeben wurde.',
  'settings.language.label': '{product} anzeigen in',
  'settings.language.save': 'Sprache ändern',

  /* --------------------------------------------------------- team & access */
  'team.title': 'Team & Zugriff',
  'team.intro':
    'Wer in Ihrer Organisation {product} nutzen darf und was er hier tun kann. Personen zur Organisation hinzuzufügen oder aus ihr zu entfernen geschieht im KORAS-Kundenportal; diese Seite regelt nur den Zugriff auf dieses Produkt.',
  'team.yours.title': 'Ihr Zugriff',
  'team.yours.signedInAs': 'Angemeldet als',
  'team.yours.role': 'Rolle in diesem Produkt',
  'team.yours.orgRoles': 'Organisationsrollen',
  'team.yours.permissions': 'Berechtigungen',
  'team.how.title': 'Wie über den Zugriff entschieden wird',
  'team.how.description':
    'Jede Organisationsrolle trägt einen Satz Berechtigungen in diesem Produkt. Die Zuordnung liegt in <code>packages/permissions/src/index.ts</code> und ist dieselbe, die die Seitenleiste und jede Routenprüfung lesen — ein aus der Navigation ausgeblendetes Modul wird an seiner URL nach derselben Regel abgewiesen, nicht bloß aus dem Menü gelassen.',
  'team.how.caption': 'Organisationsrollen und die Produktberechtigungen, die jede trägt',
  'team.how.colRole': 'Organisationsrolle',
  'team.how.colPermissions': 'Berechtigungen in diesem Produkt',
  'team.perPerson.title': 'Zuweisung pro Person',
  'team.perPerson.description':
    'Noch nicht verfügbar. Der Zugriff auf dieses Produkt wird derzeit aus der Organisationsrolle jeder Person abgeleitet, sodass jede Person mit einer Rolle in Ihrer Organisation {product} öffnen kann. Den Zugriff einer einzelnen Person unabhängig zu gewähren oder zu entziehen braucht einen Zuweisungsspeicher, den dieses Repository nicht hat; <code>packages/permissions/src/index.ts</code> nennt die eine Funktion, die sich ändert, wenn er kommt.',
  'team.perPerson.manage':
    'Sie besitzen <code>team.manage</code>; die Bedienelemente dafür erscheinen hier für Sie, sobald es sie gibt.',

  /* ----------------------------------------------------- legal page frame */
  'legal.notReviewed.label': 'Noch nicht geprüft.',
  'legal.notReviewed.text':
    'Diese Seite beschreibt, was die Software tut. Sie ist kein Rechtsdokument und wurde von niemandem geprüft, der befugt wäre, eines zu verfassen. Ersetzen Sie sie, bevor dieses Produkt verkauft wird, und übergeben Sie <code>reviewed</code>, um diesen Hinweis zu entfernen.',

  /* -------------------------------------------------------------- privacy */
  'privacy.title': 'Datenschutz',
  'privacy.metaDescription': 'Wie {product} mit personenbezogenen Daten umgeht.',
  'privacy.summary': 'Was {product} über die Personen speichert, die es nutzen, und warum.',
  'privacy.stored.title': 'Was über Sie gespeichert wird',
  'privacy.stored.p1':
    'Wenn Sie sich anmelden, speichert {product} die Kennung, die uns der Anmeldedienst Ihrer Organisation übergibt, Ihre E-Mail-Adresse und Ihren Anzeigenamen. Es speichert, zu welcher Organisation Sie gehören und welche Rolle Sie dort haben, weil diese beiden Tatsachen entscheiden, was Sie öffnen dürfen.',
  'privacy.stored.p2':
    'Alles andere in {product} sind Daten, die Ihre eigene Organisation dort abgelegt hat. Sie gehören ihr, nicht uns.',
  'privacy.who.title': 'Wer sie sehen kann',
  'privacy.who.p1':
    'Die Daten Ihrer Organisation sind von denen jeder anderen Organisation in der Datenbank selbst getrennt, durch Zeilensicherheit, nicht durch einen Filter in der Anwendung. Eine Abfrage, die vergisst, sich einzugrenzen, liefert nichts statt der Datensätze anderer.',
  'privacy.who.p2':
    'Personen, die {product} administrieren, können im Zuge von Betrieb und Support auf Daten zugreifen. Was sie tun, wird protokolliert.',
  'privacy.signin.title': 'Anmeldung',
  'privacy.signin.p1':
    '{product} sieht Ihr Passwort nie. Die Anmeldung findet beim Identitätsanbieter Ihrer Organisation statt, der uns nur mitteilt, wer Sie sind und was Sie dürfen. Ihre Sitzung ist ein Cookie, das diese Anwendung signiert, das niemand sonst lesen kann und das nur an diese Website gesendet wird.',
  'privacy.cookies.title': 'Cookies',
  'privacy.cookies.p1':
    'Drei, und alle sind notwendig: eines hält Ihre Sitzung, eines trägt das Token, das diese Anwendung an ihre eigene API weiterreicht, und eines merkt sich die von Ihnen gewählte Sprache. Es gibt kein Werbe- oder Analyse-Cookie in {product}, so wie es ausgeliefert wird.',
  'privacy.ask.title': 'Fragen zu Ihren Daten',
  'privacy.ask.contactAdmin':
    'Wenden Sie sich an die Person, die {product} in Ihrer Organisation administriert.',
  'privacy.ask.writeTo': 'Schreiben Sie an <a>{email}</a>.',

  /* ---------------------------------------------------------------- terms */
  'terms.title': 'Nutzungsbedingungen',
  'terms.metaDescription': 'Die Bedingungen, zu denen {product} bereitgestellt wird.',
  'terms.summary': 'Was Sie von {product} erwarten können, und was es von Ihnen erwartet.',
  'terms.accounts.title': 'Konten',
  'terms.accounts.p1':
    'Der Zugang zu {product} gehört einer Organisation, nicht einer Person. Ihre Organisation entscheidet, wer sich anmelden darf und was jede Person tun kann; wer aus der Organisation entfernt wird, verliert den Zugang.',
  'terms.accounts.p2':
    'Sie sind verantwortlich für das, was unter Ihrer Anmeldung geschieht. Informieren Sie Ihren Administrator umgehend, wenn Sie glauben, dass jemand anderes sie nutzt.',
  'terms.plans.title': 'Tarife',
  'terms.plans.p1':
    'Was Ihre Organisation nutzen darf, entscheidet ihr Tarif. Funktionen außerhalb davon sind entweder ausgeblendet oder als nicht verfügbar gekennzeichnet — nie stillschweigend eingeschränkt und nie in Rechnung gestellt, ohne gekauft worden zu sein.',
  'terms.plans.p2':
    'Eine Testphase endet an ihrem Datum. Dann endet der Zugriff auf tarifgebundene Funktionen, das Konto selbst bleibt bestehen, sodass sich weiterhin jemand anmelden und einen Tarif wählen kann.',
  'terms.data.title': 'Ihre Daten',
  'terms.data.p1':
    'Die Daten, die Ihre Organisation in {product} einträgt, bleiben die Ihrer Organisation. Sie werden getrennt von denen jeder anderen Organisation gespeichert und weder zum Trainieren von irgendetwas verwendet noch an irgendjemanden verkauft.',
  'terms.use.title': 'Zulässige Nutzung',
  'terms.use.p1':
    'Versuchen Sie nicht, auf die Daten einer anderen Organisation zuzugreifen, den Dienst für andere zu stören oder {product} zu nutzen, um gegen Gesetze zu verstoßen. Der Zugang kann gesperrt werden, wo eines davon geschieht.',
  'terms.changes.title': 'Änderungen',
  'terms.changes.p1':
    'Diese Bedingungen können sich ändern. Wesentliche Änderungen werden angekündigt, bevor sie wirksam werden, nicht stillschweigend angewendet.',

  /* ------------------------------------------------------------------ FAQ */
  'faq.title': 'FAQ',
  'faq.metaDescription': 'Häufige Fragen zu {product}.',
  'faq.summary': 'Die Fragen, die {product} am häufigsten gestellt werden.',
  'faq.signin.title': 'Wie melde ich mich an?',
  'faq.signin.p1':
    'Über den Identitätsanbieter Ihrer Organisation. {product} fragt nie nach einem Passwort und speichert keines — Sie werden zur Anmeldung geschickt und kommen hierher zurück. Verlangt Ihre Organisation einen zweiten Faktor, werden Sie danach gefragt und ohne ihn abgewiesen, statt zur Anmeldeseite zurückgeschleift zu werden.',
  'faq.missing.title': 'Warum sehe ich einen Bereich nicht, den andere sehen?',
  'faq.missing.p1': 'Vier Dinge entscheiden darüber, und sie schlagen absichtlich unterschiedlich fehl.',
  'faq.missing.p2':
    'Ihre <strong>Rolle</strong> entscheidet, was Sie tun dürfen; ein Bereich, für den Sie keine Berechtigung haben, ist ausgeblendet, und auch seine Adresse wird abgewiesen. Der <strong>Tarif</strong> Ihrer Organisation entscheidet, was sie gekauft hat; diese Bereiche erscheinen entweder gar nicht oder gesperrt, je nachdem, ob Sie sie hinzubuchen könnten. Die eigenen <strong>Funktionsschalter</strong> Ihrer Organisation funktionieren genauso. Und manche Bereiche gibt es nur in Installationen, die mit ihnen erzeugt wurden.',
  'faq.missing.p3':
    'Einstellungen → Allgemein nennt die Datei hinter jedem der vier — der schnellste Weg herauszufinden, an welchem Sie hängen.',
  'faq.people.title': 'Wer kann Personen hinzufügen oder entfernen?',
  'faq.people.p1':
    'Eigentümer und Administratoren Ihrer Organisation, im KORAS-Kundenportal. Team & Zugriff in {product} zeigt, wer hier Zugriff hat und was jede Rolle umfasst; jemanden zur Organisation selbst hinzuzufügen geschieht im Portal.',
  'faq.trial.title': 'Was passiert, wenn eine Testphase endet?',
  'faq.trial.p1':
    'Funktionen, die einen Tarif brauchen, stehen nicht mehr zur Verfügung, alles andere funktioniert weiter. Das Konto bleibt bestehen, und Sie können sich weiterhin anmelden — ein Konto, das mit der Testphase verschwände, könnte niemand mehr hochstufen.',
  'faq.branding.title': 'Können wir unsere eigenen Farben und unser Logo verwenden?',
  'faq.branding.p1':
    'Ja. Ein Administrator legt sie für Ihre Organisation fest, und jede angemeldete Seite übernimmt sie — Farben, Eckenradius und ein Logo für hellen und dunklen Hintergrund. Bis dahin sehen Sie das Branding des Produkts selbst.',
  'faq.language.title': 'Kann ich {product} in einer anderen Sprache nutzen?',
  'faq.language.p1':
    'Ja, sofern das Produkt eine anbietet. Der Sprachwechsler in der Kopfzeile und in den Einstellungen ändert die Oberfläche für Sie auf diesem Gerät; bis Sie wählen, wird die Spracheinstellung Ihres Browsers verwendet.',
  'faq.isolation.title': 'Sind die Daten meiner Organisation von denen aller anderen getrennt?',
  'faq.isolation.p1':
    'Ja, und zwar in der Datenbank getrennt, nicht dadurch, dass die Anwendung daran denkt, zu fragen. Eine Abfrage, die Ihre Organisation nicht nennt, liefert gar nichts.',
}
