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
  'shell.lockedUnresolved': 'Ihr Tarif konnte gerade nicht gelesen werden',
  'subscription.trial.endsIn': 'Ihre kostenlose Testphase endet in {days} Tagen.',
  'subscription.trial.endsToday': 'Ihre kostenlose Testphase endet heute.',
  'subscription.trial.open': 'Sie befinden sich in einer kostenlosen Testphase.',
  'subscription.trial.addCard': 'Zahlungsmethode hinzufügen',
  'subscription.pastDue.graceDays':
    'Ihre letzte Zahlung ist fehlgeschlagen. Der Zugang bleibt noch {days} Tage bestehen, während die Karte aktualisiert wird.',
  'subscription.pastDue.open':
    'Ihre letzte Zahlung ist fehlgeschlagen. Aktualisieren Sie Ihre Zahlungsmethode, um den Zugang zu behalten.',
  'subscription.pastDue.fixCard': 'Zahlungsmethode aktualisieren',
  'subscription.closed.trialTitle': 'Ihre kostenlose Testphase ist beendet',
  'subscription.closed.title': 'Ihr Abonnement ist beendet',
  'subscription.closed.descriptionAdmin':
    'Ihre Daten bleiben erhalten, nichts geht verloren. Wählen Sie einen Tarif, um in {product} dort weiterzumachen, wo Sie aufgehört haben.',
  'subscription.closed.descriptionMember':
    'Ihre Daten bleiben erhalten, nichts geht verloren. Ein Administrator Ihrer Organisation kann einen Tarif wählen, um {product} wieder zu öffnen.',
  'subscription.closed.action': 'Tarif wählen',

  'pricing.monthly': 'Monatlich',
  'pricing.yearly': 'Jährlich',
  'pricing.billing': 'Abrechnungszeitraum',
  'pricing.perSeatMonth': 'pro Platz und Monat',
  'pricing.perSeatYear': 'pro Platz und Jahr',
  'pricing.choose': 'Kostenlos testen',
  'pricing.priceAtCheckout': 'Preis beim Bezahlen',
  'pricing.seatsRange': '{min} bis {max} Plätze',
  'pricing.seatsFrom': 'Ab {min} Plätzen',
  'pricing.singleSeat': 'Beliebig viele Plätze',
  'pricing.custom': 'Preis auf Anfrage',
  'pricing.contactSales': 'Mit dem Vertrieb sprechen',
  'pricing.noTrial': 'Keine kostenlose Testphase. Wird mit unserem Team zu Ihren Bedingungen vereinbart.',
  'pricing.contactSubject': '{product}: ein Tarif für unsere Organisation',
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
  'login.signedOut.heading': 'Sie sind abgemeldet',
  'login.signedOut.description': 'Melden Sie sich wieder an, wann immer Sie möchten.',
  'login.note':
    'Die Anmeldung erfolgt über Ihr Organisationskonto. Es gibt kein separates {product}-Passwort, das Sie sich merken oder zurücksetzen müssten.',

  'signIn.description': 'Verwenden Sie die E-Mail-Adresse und das Passwort Ihres {product}-Kontos.',
  'signIn.form.email': 'E-Mail-Adresse',
  'signIn.form.password': 'Passwort',
  'signIn.form.submit': 'Anmelden',
  'signIn.form.submitting': 'Anmeldung läuft…',
  'signIn.form.emailRequired': 'Geben Sie Ihre E-Mail-Adresse ein.',
  'signIn.form.passwordRequired': 'Geben Sie Ihr Passwort ein.',
  'signIn.form.forgot': 'Passwort vergessen?',
  'signIn.refused': 'E-Mail-Adresse oder Passwort ist falsch.',
  'signIn.continuing': 'Angemeldet. Sie werden zur Anwendung weitergeleitet…',
  'signIn.continue': 'Weiter',
  'signIn.expired': 'Diese Anmeldung ist abgelaufen. Beginnen Sie von vorn.',
  'signIn.startAgain': 'Von vorn beginnen',
  'signIn.tooMany': 'Zu viele Versuche von hier. Versuchen Sie es in ein paar Minuten erneut.',
  'signIn.unavailable':
    'Die Anmeldung ist gerade nicht verfügbar. Versuchen Sie es in Kürze erneut.',
  'signIn.factor.heading': 'Code eingeben',
  'signIn.factor.description':
    'Öffnen Sie Ihre Authenticator-App und geben Sie den sechsstelligen Code ein, den sie anzeigt.',
  'signIn.factor.code': 'Code',
  'signIn.factor.submit': 'Weiter',
  'signIn.factor.submitting': 'Wird geprüft…',
  'signIn.factor.refused': 'Der Code ist falsch.',
  'signIn.factor.codeRequired': 'Geben Sie den Code aus Ihrer Authenticator-App ein.',
  'signIn.provider.or': 'oder',
  'signIn.provider.continueWith': 'Weiter mit {provider}',
  'signIn.provider.failed':
    'Die Anmeldung über diesen Anbieter wurde nicht abgeschlossen. Versuchen Sie es erneut oder melden Sie sich mit Ihrem Passwort an.',
  'signIn.provider.notMember':
    'Kein {product}-Konto verwendet diese E-Mail-Adresse. Bitten Sie Ihre Organisation um eine Einladung oder melden Sie sich mit Ihrem Passwort an.',
  'signIn.provider.unverified':
    'Dieser Anbieter hat Ihre E-Mail-Adresse nicht bestätigt. Melden Sie sich mit Ihrem Passwort an.',
  'signIn.provider.ambiguous':
    'Diese E-Mail-Adresse gehört zu mehr als einem Konto. Melden Sie sich mit Ihrem Passwort an.',

  /* ------------------------------------------------------ forgot password */
  'forgot.title': 'Passwort vergessen',
  'forgot.heading': 'Passwort zurücksetzen',
  'forgot.description':
    'Geben Sie die E-Mail-Adresse ein, mit der Sie sich anmelden. Gehört sie zu einem Konto bei {product}, senden wir Ihnen einen Link zum Festlegen eines neuen Passworts.',
  'forgot.form.email': 'E-Mail-Adresse',
  'forgot.form.emailRequired': 'Geben Sie Ihre E-Mail-Adresse ein.',
  'forgot.form.emailInvalid': 'Das sieht nicht wie eine E-Mail-Adresse aus.',
  'forgot.form.submit': 'Link senden',
  'forgot.form.submitting': 'Wird gesendet…',
  'forgot.sent.title': 'Prüfen Sie Ihr E-Mail-Postfach',
  'forgot.sent.description':
    'Gehört {email} zu einem Konto bei {product}, ist ein Link zum Festlegen eines neuen Passworts unterwegs. Er gilt 7 Tage und nur einmal.',
  'forgot.back': 'Zurück zur Anmeldung',
  'forgot.tooMany': 'Zu viele Anfragen von hier. Versuchen Sie es in einer Stunde erneut.',
  'forgot.unavailable':
    'Das Zurücksetzen des Passworts ist gerade nicht verfügbar. Versuchen Sie es in Kürze erneut.',

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
  'signup.form.interval': 'Abrechnung',
  'signup.form.interval.month': 'Monatlich',
  'signup.form.interval.year': 'Jährlich',
  'signup.form.seats': 'Plätze',
  'signup.form.seatsHint': 'Zwischen {min} und {max}. Sie können das später ändern.',
  'signup.form.seatsHintMin': 'Mindestens {min}. Sie können das später ändern.',
  'signup.form.noteCard':
    'Wir senden Ihnen einen Link zur Bestätigung der Adresse und fragen dann nach einer Karte. Bis zum Ende Ihrer 14-tägigen Testphase wird nichts berechnet.',
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
  'signup.error.seats': 'Wählen Sie zwischen {min} und {max} Plätzen.',
  'signup.error.seatsMin': 'Wählen Sie mindestens {min} Plätze.',
  'signup.error.interval':
    'Dieser Tarif wird so nicht angeboten. Wählen Sie eine andere Abrechnung.',

  'checkout.title': 'Zahlungsmethode hinzufügen',
  'checkout.description':
    'Ihre Adresse ist bestätigt. Hinterlegen Sie eine Karte, um Ihre 14-tägige Testphase von {product} zu starten.',
  'checkout.opening': 'Sie werden zum sicheren Bezahlvorgang weitergeleitet …',
  'checkout.open': 'Weiter zum Bezahlvorgang',
  'checkout.trialNote':
    'Bis zum Ende der Testphase wird nichts berechnet, und Sie können vorher kündigen.',
  'checkout.closed.title': 'Der Bezahlvorgang wurde geschlossen',
  'checkout.closed.description':
    'Es wurde nichts berechnet und nichts angelegt. Gehen Sie weiter zum Bezahlvorgang, um dort fortzufahren, oder kommen Sie später zurück – wir senden Ihnen einen Link.',
  'checkout.failed.title': 'Der Bezahlvorgang konnte nicht geöffnet werden',
  'checkout.failed.description':
    'Versuchen Sie es gleich noch einmal. Ihre Adresse ist bestätigt und nichts geht verloren – wir senden Ihnen einen Link, der ihn öffnet.',

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

  // ── /activate ───────────────────────────────────────────────────────────────
  'activate.title': 'Passwort festlegen',
  'activate.heading': 'Willkommen bei {product}',
  'activate.description':
    'Legen Sie ein Passwort für {email} fest, um die Einrichtung von {organization} abzuschließen.',
  'activate.form.password': 'Passwort',
  'activate.form.hint': 'Mindestens 8 Zeichen. Ihre Organisation kann mehr verlangen.',
  'activate.form.confirm': 'Passwort bestätigen',
  'activate.form.tooShort': 'Verwenden Sie mindestens 8 Zeichen.',
  'activate.form.mismatch': 'Die beiden Passwörter stimmen nicht überein.',
  'activate.form.submit': 'Passwort festlegen und weiter',
  'activate.form.submitting': 'Passwort wird festgelegt…',
  'activate.done.title': 'Ihr Passwort ist festgelegt',
  'activate.done.description':
    'Melden Sie sich mit Ihrer E-Mail-Adresse und dem soeben gewählten Passwort an.',
  'activate.done.signIn': 'Anmelden',
  'activate.incomplete.title': 'Dieser Link ist unvollständig',
  'activate.incomplete.description': 'Öffnen Sie den Link aus Ihrer Willkommens-E-Mail erneut.',
  'activate.rateLimited.title': 'Zu viele Versuche',
  'activate.rateLimited.description':
    'Warten Sie einige Minuten und öffnen Sie den Link erneut. Es ist nichts verloren gegangen.',
  'activate.invalid.title': 'Dieser Link ist nicht gültig',
  'activate.invalid.description':
    'Er wurde möglicherweise bereits verwendet oder ist abgelaufen. Wenn Sie ein Passwort festgelegt haben, melden Sie sich an; andernfalls nutzen Sie „Passwort vergessen“ auf der Anmeldeseite.',
  'activate.failed': 'Auf unserer Seite ist etwas schiefgelaufen. Warten Sie kurz und versuchen Sie es erneut.',

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

  /* ------------------------------------------------------------ analytics */
  'analytics.title': 'Auswertungen',
  'analytics.unresolved':
    'Ihr Tarif konnte gerade nicht von der KORAS-Plattform gelesen werden; es werden nur die Berichte gezeigt, die jeder Tarif enthält. Der Grund steht im Serverprotokoll dieser Installation.',
  'analytics.notIncluded.title': 'Nicht in Ihrem Tarif enthalten',
  'analytics.notIncluded.description':
    'Auswertungen gehören zu einem höheren Tarif. Ihr aktueller Tarif ist <strong>{plan}</strong>. Ein Administrator Ihrer Organisation kann den Tarif im Kontoportal ändern.',
  'analytics.notIncluded.notRecorded': 'nicht erfasst',
  'analytics.of': '{used} von {limit}',
  'analytics.previousPeriod': 'gegenüber dem Vorzeitraum',
  'analytics.trend.up': 'Gestiegen',
  'analytics.trend.down': 'Gesunken',
  'analytics.trend.unchanged': 'Unverändert',
  'analytics.kind.estimated': 'Geschätzt',
  'analytics.kind.derived': 'Abgeleitet',
  'analytics.kind.unavailable': 'Nicht verfügbar',
  'analytics.chart.asTable': 'Als Tabelle anzeigen',
  'analytics.chart.noData': 'Nichts in diesem Zeitraum.',
  'analytics.chart.value': 'Wert',
  'analytics.chart.period': 'Zeitraum',
  'analytics.table.empty': 'Für diesen Zeitraum gibt es nichts anzuzeigen.',
  'analytics.table.truncated':
    'Nur die ersten Zeilen werden gezeigt. Grenzen Sie den Zeitraum ein, um alles zu sehen.',
  'analytics.filters.period': 'Zeitraum',
  'analytics.filters.from': 'Von',
  'analytics.filters.to': 'Bis',
  'analytics.filters.apply': 'Anwenden',
  'analytics.export.download': 'Herunterladen',
  'analytics.export.notAllowed':
    'Das Herunterladen ist in Ihrem Tarif oder Ihrer Rolle nicht enthalten.',
  'analytics.export.background': 'Im Hintergrund vorbereiten',
  'analytics.export.queued':
    'Die Datei wird vorbereitet. Sie erscheint unten unter Exporte, sobald sie fertig ist.',
  'analytics.export.csv': 'CSV',
  'analytics.export.xlsx': 'Excel',
  'analytics.export.pdf': 'PDF',
  'analytics.schedule.heading': 'Geplanter Versand',
  'analytics.schedule.intro':
    'Lassen Sie sich diesen Bericht regelmäßig per E-Mail zusenden. Jeder Versand umfasst den vorherigen Tag, die vorherige Woche oder den vorherigen Monat.',
  'analytics.schedule.cadence': 'Wie oft',
  'analytics.schedule.daily': 'Täglich',
  'analytics.schedule.weekly': 'Wöchentlich',
  'analytics.schedule.monthly': 'Monatlich',
  'analytics.schedule.format': 'Format',
  'analytics.schedule.recipients': 'Senden an',
  'analytics.schedule.recipientsHint': 'E-Mail-Adressen, durch Kommas getrennt. Bis zu zehn.',
  'analytics.schedule.create': 'Planen',
  'analytics.schedule.remove': 'Entfernen',
  'analytics.schedule.empty': 'Für diesen Bericht ist nichts geplant.',
  'analytics.schedule.next': 'Nächster Versand',
  'analytics.schedule.notIncluded': 'Geplanter Versand ist in Ihrem Tarif nicht enthalten.',
  'analytics.schedule.created': 'Der Zeitplan wurde angelegt.',
  'analytics.schedule.removed': 'Der Zeitplan wurde entfernt.',
  'analytics.schedule.invalid':
    'Der Zeitplan konnte nicht angelegt werden. Prüfen Sie die Adressen und versuchen Sie es erneut.',
  'analytics.exports.heading': 'Exporte',
  'analytics.exports.intro': 'Im Hintergrund vorbereitete Dateien, bereit zum Herunterladen.',
  'analytics.exports.empty': 'Noch keine Exporte.',
  'analytics.exports.download': 'Herunterladen',
  'analytics.exports.pending': 'Wird vorbereitet…',
  'analytics.exports.failed': 'Die Datei konnte nicht vorbereitet werden.',
  'analytics.exports.retention': 'Exporte werden {days} Tage aufbewahrt.',
  'analytics.exports.gone': 'Dieser Export ist nicht mehr verfügbar.',
  'analytics.error.format': 'Dieses Format wird für diesen Bericht nicht angeboten.',
  'analytics.list.heading': 'Berichte',
  'analytics.category.overview': 'Überblick',
  'analytics.category.usage': 'Nutzung',
  'analytics.category.people': 'Personen',
  'analytics.category.billing': 'Abrechnung',
  'analytics.category.ai': 'KI',
  'analytics.category.activity': 'Aktivität',
  'analytics.category.product': 'Dieses Produkt',
  'analytics.loading': 'Der Bericht wird geladen…',
  'analytics.retry': 'Erneut versuchen',
  'analytics.error.plan': 'Ihr Tarif enthält diesen Bericht nicht.',
  'analytics.error.forbidden': 'Ihr Konto darf diesen Bericht nicht öffnen.',
  'analytics.error.filters': 'Diese Filter akzeptiert dieser Bericht nicht.',
  'analytics.error.export': 'Ihr Tarif enthält das Herunterladen von Berichten nicht.',
  'analytics.error.unavailable':
    'Auswertungen sind gerade nicht verfügbar. Der Grund steht im Serverprotokoll.',
  'analytics.error.generic': 'Etwas ist schiefgelaufen. Versuchen Sie es erneut.',

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
  'settings.appearance.title': 'Darstellung',
  'settings.appearance.description':
    'Hell, dunkel oder wie dieses Gerät eingestellt ist. Wird nur in diesem Browser gespeichert.',

  /* ---------------------------------------------------------------- files */
  'files.title': 'Dateien',
  'files.intro':
    'Was Ihre Organisation in {product} abgelegt hat. Dateien gehen direkt aus Ihrem Browser in den Speicher, der Ihrer Organisation zugewiesen ist; das Produkt führt die Liste.',
  'files.unresolved':
    'Ihr Tarif konnte gerade nicht von der KORAS-Plattform gelesen werden, daher wird kein Speicherlimit angezeigt. Hochladen funktioniert weiterhin.',
  'files.notIncluded.title': 'Nicht in Ihrem Tarif enthalten',
  'files.notIncluded.description':
    'Dateispeicher ist Teil eines höheren Tarifs. Ihr aktueller Tarif ist <strong>{plan}</strong>. Bereits Abgelegtes bleibt erhalten.',
  'files.notIncluded.notRecorded': 'nicht erfasst',
  'files.upload': 'Datei hochladen',
  'files.uploading': 'Wird hochgeladen…',
  'files.choose': 'Datei zum Hochladen auswählen',
  'files.download': 'Herunterladen',
  'files.remove': 'Löschen',
  'files.confirmRemove': '{name} löschen? Das kann nicht rückgängig gemacht werden.',
  'files.empty': 'Noch nichts abgelegt',
  'files.emptyHint': 'Laden Sie eine Datei hoch, und sie erscheint hier für alle in Ihrer Organisation.',
  'files.column.name': 'Name',
  'files.column.size': 'Größe',
  'files.column.uploadedAt': 'Hochgeladen',
  'files.column.searchable': 'Assistent',
  'files.searchable.yes': 'Durchsuchbar',
  'files.searchable.pending': 'Wird indexiert…',
  'files.searchable.no': 'Nicht durchsuchbar',
  'files.searchable.unknown': 'Nicht indiziert',
  'files.usage': '{used} von {limit} belegt',
  'files.usageUnlimited': '{used} belegt',
  'files.usageUnknown': 'Speicherlimit gerade nicht verfügbar',
  'files.provider': 'Gespeichert bei {provider}',
  'files.retry': 'Erneut versuchen',
  'files.error.plan': 'Ihr Tarif enthält das nicht, oder der Upload würde das Speicherlimit überschreiten.',
  'files.error.forbidden': 'Ihr Konto darf das nicht.',
  'files.error.notArrived': 'Die Datei ist nicht wie erwartet im Speicher angekommen. Versuchen Sie den Upload erneut.',
  'files.error.unavailable':
    'Dateispeicher ist für Ihre Organisation gerade nicht verfügbar. Der Grund steht im Serverprotokoll.',
  'files.error.generic': 'Etwas ist schiefgelaufen. Versuchen Sie es erneut.',

  /* --------------------------------------------------------------- assistant */
  'assistant.title': 'Assistent',
  'assistant.intro':
    'Fragen Sie zu dem, woran Sie gerade arbeiten. Der Assistent kann lesen, was Ihre Organisation hier hält, und Aktionen vorschlagen, die erst nach einer Freigabe ausgeführt werden.',
  'assistant.unresolved':
    'Ihr Tarif konnte gerade nicht gelesen werden, daher kann der Assistent ablehnen. Wenn das anhält, wenden Sie sich an einen Administrator.',
  'assistant.notIncluded.title': 'Nicht in Ihrem Tarif enthalten',
  'assistant.notIncluded.description':
    'Der Assistent ist nicht Teil des Tarifs <strong>{plan}</strong>. Ein Administrator Ihrer Organisation kann den Tarif im Kundenportal ändern.',
  'assistant.notIncluded.notRecorded': 'nicht erfasst',
  'assistant.open': 'Assistenten öffnen',
  'assistant.close': 'Assistenten schließen',
  'assistant.drawerTitle': 'Assistent',
  'assistant.newConversation': 'Neue Unterhaltung',
  'assistant.empty': 'Fragen Sie etwas zu Ihrer Organisation',
  'assistant.emptyHint': 'Der Assistent antwortet aus dem, was Ihre Organisation hier hält, und aus nichts anderem.',
  'assistant.you': 'Sie',
  'assistant.speaker': 'Assistent',
  'assistant.composer.label': 'Ihre Nachricht',
  'assistant.composer.placeholder': 'Fragen Sie den Assistenten…',
  'assistant.send': 'Senden',
  'assistant.sending': 'Denkt nach…',
  'assistant.retry': 'Erneut versuchen',
  'assistant.suggestions.title': 'Vorschläge',
  'assistant.suggestions.files': 'Welche Dateien haben wir?',
  'assistant.suggestions.summary': 'Fasse zusammen, was ich gerade sehe',
  'assistant.usage': '{used} von {limit} Anfragen in diesem Monat genutzt',
  'assistant.usageUnlimited': '{used} Anfragen in diesem Monat',
  'assistant.usageOverage':
    '{used} Anfragen in diesem Monat, über die {limit} Ihres Tarifs hinaus. Bisherige nutzungsabhängige Kosten: ${charges}',
  'assistant.usageUnknown': 'Das Kontingent ist gerade nicht verfügbar',
  'assistant.citations': 'Quellen',
  'assistant.activity.title': 'Letzte Aktivitäten des Assistenten',
  'assistant.activity.hint': 'Was der Assistent vorgeschlagen, ausgeführt, verweigert bekommen und entschieden hat – für die Personen, die freigeben. Nie der Inhalt eines Gesprächs.',
  'assistant.activity.empty': 'Noch nichts aufgezeichnet.',
  'assistant.pending.title': 'Wartet auf Freigabe',
  'assistant.pending.hint':
    'Der Assistent hat dies vorgeschlagen; es wird erst ausgeführt, wenn jemand es freigibt.',
  'assistant.pending.cannotDecide': 'Ein Administrator Ihrer Organisation muss das entscheiden.',
  'assistant.approve': 'Freigeben',
  'assistant.reject': 'Ablehnen',
  'assistant.deciding': 'Wird ausgeführt…',
  'assistant.operation.read': 'Liest',
  'assistant.operation.write': 'Ändert etwas',
  'assistant.operation.destructive': 'Löscht etwas',
  'assistant.operation.external': 'Verlässt das Produkt',
  'assistant.toolResult': 'Ergebnis von {tool}',
  'assistant.toolResultShow': 'Details anzeigen',
  'assistant.error.plan': 'Ihr Tarif enthält den Assistenten nicht.',
  'assistant.error.forbidden': 'Ihr Konto darf das nicht.',
  'assistant.error.limit': 'Ihre Organisation hat ihr Assistenten-Kontingent für diesen Monat aufgebraucht.',
  'assistant.error.unavailable':
    'Der Assistent ist gerade nicht verfügbar. Der Grund steht im Serverprotokoll.',
  'assistant.error.timeout': 'Der Assistent hat zu lange gebraucht. Versuchen Sie es erneut.',
  'assistant.error.generic': 'Etwas ist schiefgelaufen. Versuchen Sie es erneut.',

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

  // F20 phase 2: persistence and admin
  /* ------------------------------------------------------ language, stored */
  'settings.language.remembered':
    'Da Sie angemeldet sind, wird Ihre Wahl in Ihrem Konto gespeichert und gilt auf jedem Gerät, an dem Sie sich anmelden.',
  'settings.language.tenantTitle': 'Standard für Ihre Organisation',
  'settings.language.tenantDescription':
    'Was ein Mitglied Ihrer Organisation sieht, bevor es selbst eine Sprache wählt. Wer bereits gewählt hat, behält seine Wahl.',
  'settings.language.tenantLabel': 'Mitglieder beginnen in',
  'settings.language.tenantFollowBrowser': 'der Sprache ihres Browsers',
  'settings.language.tenantSave': 'Standard speichern',
  'settings.language.tenantSaving': 'Wird gespeichert…',
  'settings.language.tenantSaved': 'Die Standardsprache wurde gespeichert.',
  'settings.language.tenantError':
    'Die Standardsprache konnte nicht gespeichert werden. Versuchen Sie es gleich noch einmal.',
  'settings.language.tenantForbidden':
    'Nur ein Eigentümer oder Administrator kann die Standardsprache ändern.',

  /* ------------------------------------------------------------- admin */
  'admin.title': '{product} Admin',
  'admin.login.audience':
    'Für Eigentümer und Administratoren der Organisation. Eine Mehrfaktor-Authentifizierung ist erforderlich.',
  'admin.mfaRequired':
    'Eine Mehrfaktor-Authentifizierung ist erforderlich. Richten Sie einen zweiten Faktor ein und melden Sie sich erneut an.',
  'admin.forbidden': 'Diese Anwendung ist für Eigentümer und Administratoren der Organisation.',
  'admin.home.signedInAs': 'Angemeldet als {name}.',

  /* ------------------------------------------ F20 phase 2: errors and email */
  'restore.title':
    'Wiederherstellen',
  'restore.description':
    'Eine Datei aus ihrer Sicherung zurueckholen. Zwei Personen entscheiden: eine fragt an, eine andere genehmigt. Vorher wird nichts wiederhergestellt.',
  'restore.available':
    'Was wiederhergestellt werden kann',
  'restore.availableDescription':
    'Dateien mit einer Sicherungskopie. Eine geloeschte Datei erscheint hier weiterhin -- genau dafuer ist die Kopie da.',
  'restore.requests':
    'Anfragen',
  'restore.requestsDescription':
    'Jede Anfrage und ihr Stand. Auch eine abgelehnte bleibt erhalten, denn nach genau dieser wird spaeter gefragt.',
  'restore.name':
    'Datei',
  'restore.copied':
    'Kopiert',
  'restore.size':
    'Groesse',
  'restore.state':
    'Zustand',
  'restore.present':
    'Noch vorhanden',
  'restore.deleted':
    'Geloescht',
  'restore.verified':
    'Kopie geprueft',
  'restore.unverified':
    'Kopiert, nicht geprueft',
  'restore.ask':
    'Wiederherstellung anfragen',
  'restore.asking':
    'Wird angefragt...',
  'restore.cancel':
    'Abbrechen',
  'restore.reason':
    'Warum diese Datei gebraucht wird',
  'restore.reasonHint':
    'Wer die Anfrage genehmigt, liest dies. Es wird mit der Anfrage aufbewahrt.',
  'restore.overwrite':
    'Vorhandene Datei ersetzen',
  'restore.overwriteHint':
    'Ohne diese Option kommt die Datei als neue Kopie zurueck. Es wird nichts ersetzt.',
  'restore.overwriteWarning':
    'Die jetzt vorhandene Datei wird durch die Sicherung ersetzt. Wer genehmigt, muss dies gesondert bestaetigen.',
  'restore.askNewCopy':
    'Neue Kopie anfragen',
  'restore.askOverwrite':
    'Ersetzen der Datei anfragen',
  'restore.emptyBackups':
    'Noch hat keine Datei eine Sicherungskopie. Sicherungen laufen naechtlich, sobald ein Ziel konfiguriert ist.',
  'restore.emptyRequests':
    'Niemand hat eine Wiederherstellung angefragt.',
  'restore.pending':
    'Bereits angefragt',
  'restore.approve':
    'Genehmigen',
  'restore.approveOverwrite':
    'Ersetzen der Datei genehmigen',
  'restore.refuse':
    'Ablehnen',
  'restore.who':
    'Angefragt von',
  'restore.yours':
    'Sie haben dies angefragt, daher genehmigt es jemand anderes.',
  'restore.refresh':
    'Aktualisieren',
  'restore.error.forbidden':
    'Sie haben keine Berechtigung, Dateien wiederherzustellen.',
  'restore.error.unavailable':
    'Wiederherstellungen sind derzeit nicht erreichbar. Versuchen Sie es in Kuerze erneut.',
  'imports.title':
    'Datenimport',
  'imports.description':
    'Datensätze aus einer Tabelle übernehmen. Datei hochladen, Spalten zuordnen und genau sehen, was passieren würde, bevor etwas geschrieben wird.',
  'imports.startTitle':
    'Import starten',
  'imports.startDescription':
    'Wählen Sie, was importiert wird und wie mit Doppelungen umgegangen werden soll, und wählen Sie dann die Datei.',
  'imports.target':
    'Was importiert wird',
  'imports.operation':
    'Vorhandene Datensätze',
  'imports.operationHint':
    'Was mit einer Zeile geschehen soll, die zu einem vorhandenen Datensatz passt.',
  'imports.file':
    'Datei',
  'imports.ceiling':
    'Bis zu {rows} Zeilen pro Durchlauf. Zulässige Formate: {formats}.',
  'imports.mapTitle':
    'Spalten zuordnen',
  'imports.mapDescription':
    'Jede Spalte Ihrer Datei geht in genau ein Feld – oder in keines. Spalten, deren Überschrift genau passte, sind bereits zugeordnet.',
  'imports.mapColumn':
    'In welches Feld die Spalte „{column}“ geht',
  'imports.column':
    'Spalte',
  'imports.sample':
    'Erster Wert',
  'imports.field':
    'Feld',
  'imports.ignore':
    'Nicht importieren',
  'imports.check':
    'Datei prüfen',
  'imports.checking':
    'Wird geprüft…',
  'imports.discard':
    'Import verwerfen',
  'imports.tooManyRows':
    'Diese Datei hat mehr Zeilen, als ein Durchlauf aufnimmt. Teilen Sie sie und importieren Sie die Teile einzeln.',
  'imports.replaced':
    'Einige Zeichen in dieser Datei konnten nicht gelesen werden und wurden ersetzt. Prüfen Sie die Vorschau, bevor Sie fortfahren.',
  'imports.resultTitle':
    'Was passieren würde',
  'imports.summary':
    '{rows} Zeilen gelesen, davon {valid} importierbar, {errors} Probleme gefunden.',
  'imports.wroteNothing':
    'Es wurde noch nichts geschrieben. Bestätigen Sie unten, wenn die Zahlen stimmen.',
  'imports.confirm':
    'Diese Datensätze importieren',
  'imports.confirmHint':
    'Damit werden die Datensätze in {product} geschrieben. Das lässt sich auf dieser Seite nicht rückgängig machen.',
  'imports.committing':
    'Wird importiert …',
  'imports.notCommittable':
    'Dieser Import kann geprüft, aber nicht geschrieben werden. In diesem Produkt nimmt noch nichts diese Datensätze entgegen.',
  'imports.wrote':
    '{created} von {total} Datensätzen wurden importiert.',
  'imports.downloadReport':
    'Alle Probleme herunterladen',
  'imports.showReport':
    'Probleme anzeigen',
  'imports.reportCut':
    'Es werden nur die ersten Probleme aufgeführt. Beheben Sie diese und prüfen Sie die Datei erneut.',
  'imports.row':
    'Zeile',
  'imports.problem':
    'Problem',
  'imports.value':
    'Wert',
  'imports.historyTitle':
    'Letzte Importe',
  'imports.noRuns':
    'Es wurde noch nichts importiert.',
  'imports.noTargets':
    'Dieses Produkt nimmt noch keine Importe entgegen.',
  'imports.state':
    'Status',
  'imports.rows':
    'Zeilen',
  'imports.started':
    'Gestartet',
  'imports.op.create':
    'Jede Zeile als neuen Datensatz anlegen',
  'imports.op.update':
    'Nur vorhandene Datensätze aktualisieren',
  'imports.op.upsert':
    'Aktualisieren, wo es passt, sonst neu anlegen',
  'imports.op.skipDuplicate':
    'Neue Datensätze anlegen, vorhandene unberührt lassen',
  'imports.state.created':
    'Wartet auf die Zuordnung',
  'imports.state.mapped':
    'Spalten zugeordnet, noch nicht geprüft',
  'imports.state.validating':
    'Datei wird geprüft…',
  'imports.state.validated':
    'Geprüft. Es wurde nichts geschrieben.',
  'imports.state.validationFailed':
    'Probleme gefunden. Es wurde nichts geschrieben.',
  'imports.state.commitRequested':
    'Wartet auf den Import',
  'imports.state.committing':
    'Wird importiert…',
  'imports.state.committed':
    'Importiert',
  'imports.state.failed':
    'Dieser Import konnte nicht abgeschlossen werden',
  'imports.state.cancelled':
    'Abgebrochen',
  'imports.problem.required':
    'Dieses Feld wird benötigt und die Zelle ist leer',
  'imports.problem.tooLong':
    'Dieser Wert ist länger, als das Feld zulässt',
  'imports.problem.notAnOption':
    'Das ist keiner der Werte, die das Feld annimmt',
  'imports.problem.integer':
    'Hier wird eine ganze Zahl erwartet',
  'imports.problem.decimal':
    'Hier wird eine Zahl erwartet',
  'imports.problem.boolean':
    'Hier wird Ja oder Nein erwartet',
  'imports.problem.date':
    'Hier wird ein Datum im Format JJJJ-MM-TT erwartet',
  'imports.problem.email':
    'Das sieht nicht nach einer E-Mail-Adresse aus',
  'imports.problem.extraCells':
    'Diese Zeile hat mehr Zellen, als die Datei Spalten hat',
  'imports.problem.ambiguousDecimal':
    'Das lässt sich auf zwei Arten lesen, die sich um das Tausendfache unterscheiden. Schreiben Sie es ohne Tausendertrennzeichen.',
  'imports.problem.duplicateInFile':
    'Eine andere Zeile derselben Datei hat diesen Wert bereits',
  'imports.error.forbidden':
    'Sie haben keine Berechtigung, Datensätze zu importieren.',
  'imports.error.unavailable':
    'Importe sind derzeit nicht erreichbar. Bitte versuchen Sie es in Kürze erneut.',
  'audit.title':
    'Prüfprotokoll',
  'audit.description':
    'Was in Ihrer Organisation geschehen ist: wer was mit welchem Datensatz getan hat und wie es ausging. Einträge werden so lange aufbewahrt, wie es ihre Art erfordert, und nicht länger.',
  'audit.filters':
    'Filter',
  'audit.action':
    'Aktion',
  'audit.actor':
    'Person',
  'audit.outcome':
    'Ergebnis',
  'audit.classification':
    'Art',
  'audit.any':
    'Alle',
  'audit.apply':
    'Suchen',
  'audit.clear':
    'Zurücksetzen',
  'audit.searching':
    'Wird gesucht…',
  'audit.empty':
    'Es wurde noch nichts aufgezeichnet.',
  'audit.emptyFiltered':
    'Zu diesen Filtern gibt es nichts.',
  'audit.more':
    'Mehr anzeigen',
  'audit.when':
    'Wann',
  'audit.what':
    'Aktion',
  'audit.who':
    'Person',
  'audit.target':
    'Datensatz',
  'audit.result':
    'Ergebnis',
  'audit.kind':
    'Art',
  'audit.details':
    'Details',
  'audit.exportTitle':
    'Export',
  'audit.exportDescription':
    'Erstellen Sie eine Kopie der Einträge, die Ihren Filtern entsprechen. Die Datei wird im Hintergrund erzeugt und bleibt sieben Tage verfügbar.',
  'audit.exportFormat':
    'Format',
  'audit.exportStart':
    'Export starten',
  'audit.exportPending':
    'Aktualisieren',
  'audit.exportDownload':
    'Herunterladen',
  'audit.exportEmpty':
    'Noch keine Exporte.',
  'audit.exportRows.one':
    '{rows} Eintrag',
  'audit.exportRows.other':
    '{rows} Einträge',
  'audit.restricted':
    'Manche Arten von Einträgen dürfen nur Eigentümer oder Administratoren lesen.',
  'audit.error.forbidden':
    'Sie haben keine Berechtigung, das Prüfprotokoll zu lesen.',
  'audit.error.unavailable':
    'Das Prüfprotokoll konnte derzeit nicht gelesen werden.',
  'settings.values.title': 'Organisationseinstellungen',
  'settings.values.intro': 'Diese gelten für alle in {product}. Einzelne Personen können manche davon für sich ändern.',
  'settings.values.save': 'Speichern',
  'settings.values.saving': 'Wird gespeichert',
  'settings.values.modified': 'Hier geändert',
  'settings.values.inherited': 'Plattform-Standard',
  'settings.values.reset': 'Zurücksetzen',
  'settings.values.resetTo': 'Setzt zurück auf {value}',
  'settings.values.listHint': 'Mit Kommas trennen',
  'settings.values.on': 'Ein',
  'settings.values.off': 'Aus',
  'settings.values.saved': 'Gespeichert.',
  'settings.values.error': 'Das konnte nicht gespeichert werden. Prüfen Sie die Werte und versuchen Sie es erneut.',
  'settings.values.forbidden': 'Nur Administratoren können Einstellungen für die Organisation ändern.',
  'settings.values.unavailable': 'Die Einstellungen können derzeit nicht geladen werden.',
  'preferences.title': 'Meine Einstellungen',
  'preferences.intro': 'Diese gelten für Sie, auf jedem Gerät, an dem Sie sich anmelden. Was Sie nicht festlegen, folgt Ihrer Organisation.',
  'preferences.modified': 'Ihre Wahl',
  'preferences.inherited': 'Von Ihrer Organisation',
  'preferences.resetTo': 'Kehrt zurück zu {value}',
  'preferences.saved': 'Gespeichert.',
  'preferences.error': 'Das konnte nicht gespeichert werden. Prüfen Sie die Werte und versuchen Sie es erneut.',
  // The settings catalogue, rendered by the organisation's settings page
  // and by My preferences. Looked up from each definition's `label_key`, so
  // these keys are named by `settings_catalogue/standard.py` rather than by
  // any component -- see the exemption in `product-i18n.test.ts`.
  'settings.def.general.timezone.label': 'Zeitzone',
  'settings.def.general.timezone.description': 'Die Zeitzone, in der Datum und Uhrzeit angezeigt werden.',
  'settings.def.general.language.label': 'Sprache',
  'settings.def.general.language.description': 'Die Sprache, in der dieses Produkt angezeigt wird. Automatisch folgt dem Browser.',
  'settings.def.general.dateFormat.label': 'Datumsformat',
  'settings.def.general.dateFormat.description': 'Wie Datumsangaben geschrieben werden.',
  'settings.def.general.timeFormat.label': 'Zeitformat',
  'settings.def.general.timeFormat.description': 'Ob Uhrzeiten im 12- oder 24-Stunden-Format angezeigt werden.',
  'settings.def.general.currency.label': 'Währung',
  'settings.def.general.currency.description': 'Die Währung, in der Beträge für alle in dieser Organisation angezeigt werden.',
  'settings.def.general.firstDayOfWeek.label': 'Wochenbeginn',
  'settings.def.general.firstDayOfWeek.description': 'Mit welchem Tag eine Kalenderwoche beginnt.',
  'settings.def.ui.theme.label': 'Design',
  'settings.def.ui.theme.description': 'Hell, dunkel oder wie an diesem Gerät eingestellt.',
  'settings.def.ui.density.label': 'Anzeigedichte',
  'settings.def.ui.density.description': 'Wie viel Abstand die Oberfläche um Elemente lässt.',
  'settings.def.ui.sidebarCollapsed.label': 'Seitenleiste eingeklappt starten',
  'settings.def.ui.sidebarCollapsed.description': 'Jede Seite mit schmaler Navigation öffnen.',
  'settings.def.ui.defaultLandingPage.label': 'Startseite',
  'settings.def.ui.defaultLandingPage.description': 'Wohin die Anmeldung führt.',
  'settings.def.grid.pageSize.label': 'Zeilen pro Seite',
  'settings.def.grid.pageSize.description': 'Wie viele Zeilen eine Tabelle auf einmal zeigt.',
  'settings.def.grid.pageSizeOptions.label': 'Auswahl für Zeilen pro Seite',
  'settings.def.grid.pageSizeOptions.description': 'Die Größen, aus denen in einer Tabelle gewählt werden kann.',
  'settings.def.grid.paginationEnabled.label': 'Lange Tabellen paginieren',
  'settings.def.grid.paginationEnabled.description': 'Lange Tabellen auf Seiten aufteilen statt als eine lange Liste.',
  'settings.def.grid.stickyHeader.label': 'Tabellenüberschriften fixieren',
  'settings.def.grid.stickyHeader.description': 'Überschriften bleiben stehen, während die Zeilen scrollen.',
  'settings.def.grid.rowDensity.label': 'Zeilenhöhe',
  'settings.def.grid.rowDensity.description': 'Wie hoch Tabellenzeilen sind.',
  'settings.def.grid.allowColumnResize.label': 'Spaltenbreite anpassbar',
  'settings.def.grid.allowColumnResize.description':
    'Spaltenränder lassen sich ziehen, um Spalten breiter oder schmaler zu machen.',
  'settings.def.grid.allowColumnReorder.label': 'Spalten verschiebbar',
  'settings.def.grid.allowColumnReorder.description':
    'Spalten lassen sich in einer Tabelle nach links oder rechts verschieben.',
  'settings.def.grid.rememberColumns.label': 'Spaltenlayout merken',
  'settings.def.grid.rememberColumns.description':
    'Breiten und Reihenfolge behalten, auf diesem Gerät.',
  // ── Benachrichtigungen ────────────────────────────────────────────────────
  'notifications.title': 'Benachrichtigungen',
  'notifications.unread': '{count} ungelesen',
  'notifications.empty': 'Nichts nachzuholen',
  'notifications.emptyHint': 'Sobald etwas Ihre Aufmerksamkeit braucht, erscheint es hier.',
  'notifications.markAllRead': 'Alle als gelesen markieren',
  'notifications.markRead': 'Als gelesen markieren',
  'notifications.dismiss': 'Entfernen',
  'notifications.close': 'Benachrichtigungen schliessen',
  'notifications.viewAll': 'Alle Benachrichtigungen ansehen',
  'notifications.pageTitle': 'Benachrichtigungen',
  'notifications.pageDescription': 'Alles, was das Produkt Ihnen mitgeteilt hat, das Neueste zuerst.',
  'notifications.hiddenTitle': 'Benachrichtigungen sind ausgeschaltet',
  'notifications.hiddenBody': 'Sie haben Benachrichtigungen im Produkt ausgeschaltet. In Ihren Einstellungen koennen Sie sie wieder einschalten.',
  'settings.def.notifications.inAppEnabled.label': 'Benachrichtigungen im Produkt',
  'settings.def.notifications.inAppEnabled.description': 'Benachrichtigungen anzeigen, während Sie angemeldet sind.',
  'settings.def.notifications.emailEnabled.label': 'Benachrichtigungen per E-Mail',
  'settings.def.notifications.emailEnabled.description':
    'Zusätzlich eine E-Mail senden, wenn etwas auf Sie wartet.',
  'settings.def.files.maxUploadSizeMb.label': 'Maximale Dateigröße',
  'settings.def.files.maxUploadSizeMb.description': 'Die größte einzelne Datei, die hier hochgeladen werden darf, in Megabyte.',
  'settings.def.files.allowedExtensions.label': 'Erlaubte Dateitypen',
  'settings.def.files.allowedExtensions.description': 'Welche Dateiendungen hochgeladen werden dürfen.',
  'settings.def.files.previewEnabled.label': 'Dateivorschau',
  'settings.def.files.previewEnabled.description': 'Eine Vorschau anzeigen statt nur des Dateinamens.',
  'settings.def.reporting.defaultDateRange.label': 'Standardzeitraum',
  'settings.def.reporting.defaultDateRange.description': 'Der Zeitraum, mit dem ein Bericht geöffnet wird.',
  'settings.def.reporting.defaultExportFormat.label': 'Standard-Exportformat',
  'settings.def.reporting.defaultExportFormat.description': 'Das Format, das ein Export zuerst anbietet.',
  'settings.def.accessibility.reducedMotion.label': 'Bewegung reduzieren',
  'settings.def.accessibility.reducedMotion.description': 'Animationen auf ein Minimum beschränken.',
  'settings.def.accessibility.highContrast.label': 'Höherer Kontrast',
  'settings.def.accessibility.highContrast.description': 'Stärkerer Kontrast zwischen Text und Hintergrund.',
  'settings.def.accessibility.fontScale.label': 'Textgröße',
  'settings.def.accessibility.fontScale.description': 'Ein Faktor, der auf die Textgröße angewendet wird.',
  // The seven groups the two pages lay their settings out in.
  'settings.category.general': 'Allgemein',
  'settings.category.appearance': 'Darstellung',
  'settings.category.grid': 'Tabellen',
  'settings.category.notifications': 'Benachrichtigungen',
  'settings.category.files': 'Dateien',
  'settings.category.reporting': 'Berichte',
  'settings.category.accessibility': 'Barrierefreiheit',
  // Option labels, shared by value: `compact` means the same wherever it
  // appears, and two entries for one word is two a translator must keep level.
  'settings.option.auto': 'Automatisch',
  'settings.option.system': 'Wie dieses Gerät',
  'settings.option.light': 'Hell',
  'settings.option.dark': 'Dunkel',
  'settings.option.comfortable': 'Komfortabel',
  'settings.option.compact': 'Kompakt',
  'settings.option.iso': '2026-09-19',
  'settings.option.dmy': '19.09.2026',
  'settings.option.mdy': '09/19/2026',
  'settings.option.long': '19. September 2026',
  'settings.option.monday': 'Montag',
  'settings.option.sunday': 'Sonntag',
  'settings.option.saturday': 'Samstag',
  'settings.option.never': 'Nie',
  'settings.option.daily': 'Täglich',
  'settings.option.weekly': 'Wöchentlich',
  'settings.option.last7': 'Letzte 7 Tage',
  'settings.option.last30': 'Letzte 30 Tage',
  'settings.option.last90': 'Letzte 90 Tage',
  'settings.option.lastYear': 'Letztes Jahr',
  'settings.option.12h': '12 Stunden',
  'settings.option.24h': '24 Stunden',
  'settings.option.csv': 'CSV',
  'settings.option.xlsx': 'Excel',
  'settings.option.pdf': 'PDF',
  // Die Seitensteuerung der gemeinsamen Tabelle.
  'grid.pagination': 'Seitennavigation',
  'grid.rowsPerPage': 'Zeilen pro Seite',
  'grid.previous': 'Zurück',
  'grid.next': 'Weiter',
  'grid.showing': '{from} bis {to} von {total}',
  'grid.page': 'Seite {page} von {pages}',
  'grid.moveColumnLeft': '{column} nach links verschieben',
  'grid.moveColumnRight': '{column} nach rechts verschieben',
  'errors.tokenInvalid': 'Ihre Sitzung ist abgelaufen. Melden Sie sich erneut an.',
  'errors.tenantInactive': 'Ihre Organisation ist in diesem Produkt nicht aktiv.',
  'errors.roleRequired':
    'Das können nur Eigentümer oder Administratoren Ihrer Organisation tun.',
  'errors.permissionMissing': 'Ihre Rolle umfasst das nicht.',
  'errors.entitlementMissing': 'Ihr Tarif enthält das nicht.',
  'errors.storageLimitExceeded':
    'Dieser Upload würde den in Ihrem Tarif enthaltenen Speicher überschreiten.',
  'errors.fileNotFound': 'Diese Datei existiert nicht mehr.',
  'errors.uploadNotArrived':
    'Die Datei ist nicht wie erwartet im Speicher angekommen. Versuchen Sie den Upload erneut.',
  'errors.uploadSizeMismatch':
    'Die hochgeladene Datei hat nicht die angekündigte Größe. Versuchen Sie den Upload erneut.',
  'errors.backupNotFound':
    'Von dieser Datei existiert keine Sicherung, aus der wiederhergestellt werden könnte.',
  'errors.restoreNotFound':
    'Diese Wiederherstellungsanfrage existiert nicht.',
  'errors.restoreNotTransitionable':
    'Über diese Wiederherstellungsanfrage wurde bereits entschieden.',
  'errors.restoreAlreadyRequested':
    'Für diese Datei wartet bereits eine Wiederherstellung auf eine Entscheidung.',
  'errors.restoreOverwriteUnconfirmed':
    'Diese Anfrage ersetzt die vorhandene Datei. Genehmigen Sie sie ausdrücklich als Ersetzung, oder fordern Sie stattdessen eine neue Kopie an.',
  'errors.importTargetNotFound':
    'Dieses Produkt nimmt keinen Import dieser Art entgegen.',
  'errors.importRunNotFound':
    'Dieser Import wurde nicht gefunden.',
  'errors.importMappingRefused':
    'Die Spalten lassen sich so nicht zuordnen. Die Meldung nennt, welche.',
  'errors.importFileUnreadable':
    'Diese Datei konnte nicht gelesen werden. Prüfen Sie, ob es eine CSV-Datei mit Kopfzeile ist.',
  'errors.importTooManyRows':
    'Diese Datei hat mehr Zeilen, als ein Import aufnimmt. Teilen Sie sie und importieren Sie die Teile einzeln.',
  'errors.importOperationRefused':
    'Das darf dieser Import nicht tun.',
  'errors.importNotTransitionable':
    'Dieser Import ist weiter fortgeschritten; das ist jetzt nicht mehr möglich.',
  'errors.importQueueUnavailable':
    'Die Hintergrundverarbeitung ist nicht eingerichtet, daher kann diese Datei nicht geprüft werden. Das muss administrativ konfiguriert werden.',
  'errors.importNotCommittable':
    'Dieser Import kann geprüft, aber nicht geschrieben werden. In diesem Produkt nimmt noch nichts diese Datensätze entgegen.',
  'errors.importFileTooLarge':
    'Diese Datei ist größer, als ein Import einlesen kann. Teilen Sie sie und importieren Sie die Teile einzeln.',
  'errors.uploadRefusedByPolicy':
    'Diese Datei ist nicht zulässig. Prüfen Sie Größe und Dateityp gegen die Einstellungen Ihrer Organisation.',
  'errors.fileUnderHold':
    'Diese Datei kann nicht gelöscht werden: Eine rechtliche Aufbewahrungspflicht hält sie. Nach deren Aufhebung ist das Löschen möglich.',
  'errors.fileQuarantined':
    'Diese Datei wird zurückgehalten, weil eine Sicherheitsprüfung sie nicht als unbedenklich eingestuft hat. Wenden Sie sich an eine Administratorin oder einen Administrator, wenn Sie sie benötigen.',
  'errors.notificationNotFound':
    'Diese Benachrichtigung gibt es nicht mehr. Moeglicherweise wurde sie bereits gelesen oder entfernt.',
  'errors.settingNotFound':
    'Diese Einstellung gibt es nicht. Laden Sie die Seite neu, um die aktuelle Liste zu sehen.',
  'errors.settingValueInvalid':
    'Dieser Wert ist für diese Einstellung nicht zulässig. Der erlaubte Bereich steht daneben.',
  'errors.settingScopeRefused':
    'Diese Einstellung gilt für die gesamte Organisation und kann hier nicht geändert werden.',
  'errors.holdNotFound':
    'Diese Aufbewahrungssperre gibt es nicht.',
  'errors.holdNotTransitionable':
    'Über diese Aufbewahrungssperre wurde bereits entschieden; laden Sie die Liste neu, um den aktuellen Stand zu sehen.',
  'errors.holdInvalidWindow':
    'Eine Aufbewahrungssperre kann nicht enden, bevor sie beginnt.',
  'errors.auditEventNotFound':
    'Dieses Prüfereignis gibt es nicht.',
  'errors.storageUnavailable': 'Der Dateispeicher ist derzeit nicht verfügbar.',
  'errors.reportNotFound': 'Diesen Bericht gibt es nicht.',
  'errors.scheduleNotFound': 'Diesen Zeitplan gibt es nicht mehr.',
  'errors.exportNotFound': 'Diesen Export gibt es nicht mehr.',
  'errors.exportFormatUnknown': 'Dieses Exportformat ist unbekannt.',
  'errors.exportFormatUnsupported': 'Dieser Bericht kann nicht in diesem Format exportiert werden.',
  'errors.filterInvalid': 'Einer der Filter ist für diesen Bericht nicht gültig.',
  'errors.recipientInvalid': 'Einer der Empfänger ist keine E-Mail-Adresse.',
  'errors.periodNotAFilter': 'Den Zeitraum eines geplanten Berichts bestimmt sein Rhythmus.',
  'errors.reportFailed': 'Der Bericht konnte nicht erstellt werden. Versuchen Sie es später erneut.',
  'errors.toolDenied': 'Ihre Rolle erlaubt das im Assistenten nicht.',

  /* ----------------------------------------------------------- governance */
  'governance.title': 'Governance',
  'governance.description':
    'Rechtliche Sperren und wie lange diese Organisation Gespeichertes aufbewahrt. Eine Sperre verhindert das Löschen von allem, was sie umfasst, auch durch die nächtlichen Aufbewahrungsläufe.',
  'governance.holds': 'Rechtliche Sperren',
  'governance.holdsDescription':
    'Jede Sperre und ihr Stand. Eine aufgehobene bleibt erhalten, denn nach ihr wird später gefragt.',
  'governance.reason': 'Warum diese Sperre nötig ist',
  'governance.reasonHint':
    'Nennen Sie den Vorgang. Das liest, wer sie genehmigt, und jeder, der die Sperre später prüft.',
  'governance.scope': 'Was sie umfasst',
  'governance.scopeTenant': 'Alles, was diese Organisation hat',
  'governance.scopeFiles': 'Nur Dateien',
  'governance.scopeAudit': 'Nur Audit-Einträge',
  'governance.endsAt': 'Endet am (optional)',
  'governance.endsAtHint':
    'Leer lassen für eine Sperre ohne Ende. Eine offene Sperre bewahrt alles auf, bis jemand sie aufhebt.',
  'governance.ask': 'Sperre beantragen',
  'governance.asking': 'Wird beantragt…',
  'governance.status': 'Status',
  'governance.inForce': 'Derzeit in Kraft',
  'governance.notInForce': 'Hält derzeit nichts',
  'governance.who': 'Beantragt von',
  'governance.yours': 'Darüber muss jemand anderes als Sie entscheiden.',
  'governance.approve': 'Genehmigen',
  'governance.release': 'Sperre aufheben',
  'governance.releaseWarning':
    'Was sie umfasst, kann ab dem nächsten nächtlichen Lauf wieder gelöscht werden.',
  'governance.emptyHolds': 'Es wurde keine Sperre beantragt.',
  'governance.refresh': 'Aktualisieren',
  'governance.retention': 'Aufbewahrungsdauer',
  'governance.retentionDescription':
    'Tage, nach Art. Ein leeres Feld bedeutet den Standard der Plattform für diese Art.',
  'governance.retentionFloorHint':
    'Sie können länger als den Standard verlangen, nie kürzer: eine kleinere Zahl wird angenommen, es gilt der längere Wert. Höchstens 3650 Tage.',
  'governance.days': 'Tage',
  'governance.save': 'Speichern',
  'governance.saving': 'Wird gespeichert…',
  'governance.saved': 'Gespeichert.',
  'governance.kind.auditActivity': 'Alltägliche Aktivitätseinträge',
  'governance.kind.audit': 'Audit-Einträge',
  'governance.kind.auditSecurity': 'Sicherheitseinträge',
  'governance.kind.storageStandard': 'Gewöhnliche Dateien',
  'governance.kind.storageSensitive': 'Vertrauliche Dateien',
  'governance.kind.storageRestricted': 'Streng vertrauliche Dateien',
  'governance.error.forbidden':
    'Dazu fehlt Ihnen die Berechtigung. Sperren setzen oder aufheben erfordert die Sperrberechtigung; genehmigen oder aufheben erfordert eine Inhaberin oder Administratorin, die sie nicht beantragt hat.',
  'governance.error.unavailable':
    'Governance konnte gerade nicht gelesen werden. Es wurde nichts geändert.',
}
