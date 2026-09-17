/**
 * The English catalogue: the source of truth for every key.
 *
 * Grouped by the surface that shows the string. Keys name the *place* and the
 * *role* of a string, never its English wording -- `login.note` survives a
 * rewording, `login.noSeparatePassword` does not.
 *
 * Placeholders are `{name}`, single-braced. Some messages carry inline markup
 * -- `<code>…</code>`, `<a>…</a>`, `<strong>…</strong>` -- and those are
 * rendered through `rich()` in the UI package, which maps each tag to an
 * element. The tags here are a vocabulary, not HTML: a catalogue string is
 * never set as innerHTML.
 *
 * `as const` is what gives every other catalogue its type. Add a key here and
 * `de.ts` stops compiling until it has one too.
 */
export const en = {
  /* ---------------------------------------------------------------- common */
  'common.skipToMain': 'Skip to main content',
  'common.signIn': 'Sign in',
  'common.getStarted': 'Get started',
  'common.goToDashboard': 'Go to dashboard',
  'common.none': 'None',
  'common.language': 'Language',
  'common.copyright': '© {year} {product}',

  /* --------------------------------------------------- authenticated shell */
  'shell.openNavigation': 'Open navigation',
  'shell.closeNavigation': 'Close navigation',
  'shell.expandSidebar': 'Expand the sidebar',
  'shell.collapseSidebar': 'Collapse the sidebar',
  'shell.productNavigation': 'Product navigation',
  'shell.navigationLabel': 'Product',
  'shell.drawerNavigationLabel': 'Product, drawer',
  'shell.workspace': 'Workspace: ',
  'shell.accountMenu': 'Account menu',
  'shell.signedIn': 'Signed in',
  'shell.manageSubscription': 'Manage subscription',
  'shell.opensPortal': '(opens the Koras account portal)',
  'shell.signOut': 'Sign out',
  'shell.appearance': 'Appearance',
  'shell.themeLight': 'Light',
  'shell.themeSystem': 'System',
  'shell.themeDark': 'Dark',
  'shell.lockedPlan': 'Not included in your plan',
  'shell.lockedUnresolved': 'Your plan could not be read just now',
  'shell.lockedFeature': 'Not enabled for your organisation',

  'subscription.trial.endsIn': 'Your free trial ends in {days} days.',
  'subscription.trial.endsToday': 'Your free trial ends today.',
  'subscription.trial.open': 'You are on a free trial.',
  'subscription.trial.addCard': 'Add a payment method',
  'subscription.pastDue.graceDays':
    'Your last payment did not go through. Access continues for {days} days while the card is updated.',
  'subscription.pastDue.open': 'Your last payment did not go through. Update your payment method to keep access.',
  'subscription.pastDue.fixCard': 'Update payment method',
  'subscription.closed.trialTitle': 'Your free trial has ended',
  'subscription.closed.title': 'Your subscription has ended',
  'subscription.closed.descriptionAdmin':
    'Your data is kept and nothing is lost. Choose a plan to pick up where you left off in {product}.',
  'subscription.closed.descriptionMember':
    'Your data is kept and nothing is lost. An administrator of your organisation can choose a plan to reopen {product}.',
  'subscription.closed.action': 'Choose a plan',

  'pricing.monthly': 'Monthly',
  'pricing.yearly': 'Yearly',
  'pricing.billing': 'Billing period',
  'pricing.perSeatMonth': 'per seat, per month',
  'pricing.perSeatYear': 'per seat, per year',
  'pricing.choose': 'Start free trial',
  'pricing.priceAtCheckout': 'Price shown at checkout',
  'pricing.seatsRange': '{min} to {max} seats',
  'pricing.seatsFrom': 'From {min} seats',
  'pricing.singleSeat': 'Any number of seats',
  'pricing.custom': 'Custom pricing',
  'pricing.contactSales': 'Talk to sales',
  'pricing.noTrial': 'No free trial. Agreed with our team, on your terms.',
  'pricing.contactSubject': '{product}: a plan for our organisation',
  'shell.roleAdministrator': 'Administrator',
  'shell.roleMember': 'Member',

  'accessDenied.title': 'You do not have access to this page',
  'accessDenied.description':
    'Your account is signed in, but it does not have permission for this area. An administrator in your organisation can change that.',

  /* ------------------------------------------------------- public header */
  'header.primary': 'Primary',
  'header.primarySmall': 'Primary, small screen',
  'header.openMenu': 'Open menu',
  'header.closeMenu': 'Close menu',
  'footer.builtBy': 'Built by',
  'footer.on': '{product} on {network}',

  /* ------------------------------------------------- the drawn app frame */
  'appFrame.workspace': 'workspace',
  'appFrame.overview': 'Operations overview',
  'appFrame.open': 'Open',
  'appFrame.dueToday': 'Due today',
  'appFrame.blocked': 'Blocked',
  'appFrame.inProgress': 'In progress',
  'appFrame.waiting': 'Waiting',
  'appFrame.scheduled': 'Scheduled',
  'appFrame.row.onboarding': 'Onboarding · Northwind',
  'appFrame.row.renewal': 'Renewal review · Contoso',
  'appFrame.row.access': 'Access request · Fabrikam',
  'appFrame.row.export': 'Quarterly export',

  /* -------------------------------------------------------------- sign-in */
  'login.title': 'Sign in',
  'login.heading': 'Sign in to {product}',
  'login.description':
    "You will be taken to your organisation's sign-in and brought straight back.",
  'login.noAccount': 'No account yet?',
  'login.signedOut.heading': 'You are signed out',
  'login.signedOut.description': 'Sign in again whenever you are ready.',
  'login.note':
    'Signing in uses your organisation account. There is no separate {product} password to remember or reset.',

  'signIn.description': 'Use the email address and password for your {product} account.',
  'signIn.form.email': 'Email address',
  'signIn.form.password': 'Password',
  'signIn.form.submit': 'Sign in',
  'signIn.form.submitting': 'Signing in…',
  'signIn.form.emailRequired': 'Enter your email address.',
  'signIn.form.passwordRequired': 'Enter your password.',
  'signIn.form.forgot': 'Forgot your password?',
  'signIn.refused': 'The email address or password is wrong.',
  'signIn.continuing': 'Signed in. Taking you to the application…',
  'signIn.continue': 'Continue',
  'signIn.expired': 'This sign-in has expired. Start again.',
  'signIn.startAgain': 'Start again',
  'signIn.tooMany': 'Too many attempts from here. Try again in a few minutes.',
  'signIn.unavailable': 'Signing in is not available right now. Try again shortly.',
  'signIn.factor.heading': 'Enter your code',
  'signIn.factor.description':
    'Open your authenticator app and enter the six-digit code it shows.',
  'signIn.factor.code': 'Code',
  'signIn.factor.submit': 'Continue',
  'signIn.factor.submitting': 'Checking…',
  'signIn.factor.refused': 'The code is wrong.',
  'signIn.factor.codeRequired': 'Enter the code from your authenticator app.',
  'signIn.provider.or': 'or',
  'signIn.provider.continueWith': 'Continue with {provider}',
  'signIn.provider.failed':
    'The sign-in with that provider did not finish. Try again, or sign in with your password.',
  'signIn.provider.notMember':
    'No {product} account uses that email address. Ask your organization to invite you, or sign in with your password.',
  'signIn.provider.unverified':
    'That provider has not verified your email address. Sign in with your password.',
  'signIn.provider.ambiguous':
    'That email address belongs to more than one account. Sign in with your password.',

  /* ------------------------------------------------------ forgot password */
  'forgot.title': 'Forgot password',
  'forgot.heading': 'Reset your password',
  'forgot.description':
    'Enter the email address you sign in with. If it belongs to an account on {product}, we will send a link to set a new password.',
  'forgot.form.email': 'Email address',
  'forgot.form.emailRequired': 'Enter your email address.',
  'forgot.form.emailInvalid': 'That does not look like an email address.',
  'forgot.form.submit': 'Send the link',
  'forgot.form.submitting': 'Sending…',
  'forgot.sent.title': 'Check your email',
  'forgot.sent.description':
    'If {email} belongs to an account on {product}, a link to set a new password is on its way. It works for 7 days and once.',
  'forgot.back': 'Back to sign in',
  'forgot.tooMany': 'Too many requests from here. Try again in an hour.',
  'forgot.unavailable': 'Resetting a password is not available right now. Try again shortly.',

  /* --------------------------------------------------------------- signup */
  'signup.title': 'Get started',
  'signup.heading': 'Start with {product}',
  'signup.description':
    'Tell us where to send your confirmation link. Nothing is created until you open it.',
  'signup.haveAccount': 'Already have an account?',
  'signup.form.organisation': 'Organisation',
  'signup.form.email': 'Work email',
  'signup.form.name': 'Your name',
  'signup.form.optional': 'Optional.',
  'signup.form.plan': 'Plan',
  'signup.form.interval': 'Billing',
  'signup.form.interval.month': 'Monthly',
  'signup.form.interval.year': 'Yearly',
  'signup.form.seats': 'Seats',
  'signup.form.seatsHint': 'Between {min} and {max}. You can change this later.',
  'signup.form.seatsHintMin': 'At least {min}. You can change this later.',
  'signup.form.submit': 'Create account',
  'signup.form.submitting': 'Creating your account',
  'signup.form.note':
    'We will email you a link to confirm the address. Nothing is created until you open it.',
  'signup.form.noteCard':
    'We will email you a link to confirm the address, then ask for a card. Nothing is charged until your 14-day trial ends.',
  'signup.sent.title': 'Check your email',
  'signup.sent.message':
    'Check {email} for a link to confirm your address. Nothing is created until you do.',
  'signup.error.tooMany': 'Too many attempts from here. Please try again shortly.',
  'signup.error.planUnavailable':
    'That plan is not available to sign up for online. Please contact us.',
  'signup.error.checkDetails': 'Check the details and try again.',
  'signup.error.generic': 'Something went wrong. Please try again.',
  'signup.error.email': 'Enter your email address.',
  'signup.error.organisation': 'What is your organisation called?',
  'signup.error.notAvailable': 'Signing up is not available right now.',
  'signup.error.notConfigured': 'Signing up is not available yet. Please contact us.',
  'signup.error.unreachable': 'We could not reach the signup service.',
  'signup.error.seats': 'Choose between {min} and {max} seats.',
  'signup.error.seatsMin': 'Choose at least {min} seats.',
  'signup.error.interval': 'That plan is not sold that way. Choose another billing option.',

  'checkout.title': 'Add a payment method',
  'checkout.description':
    'Your address is confirmed. Add a card to start your 14-day trial of {product}.',
  'checkout.opening': 'Taking you to the secure checkout…',
  'checkout.open': 'Continue to checkout',
  'checkout.trialNote': 'Nothing is charged until the trial ends, and you can cancel before then.',
  'checkout.closed.title': 'The checkout was closed',
  'checkout.closed.description':
    'Nothing was charged and nothing was created. Continue to the checkout to pick up where you left off, or come back later — we will email you a link.',
  'checkout.failed.title': 'The checkout could not be opened',
  'checkout.failed.description':
    'Try again in a moment. Your address is confirmed and nothing is lost — we will email you a link that opens it.',

  'requestAccess.heading': 'Get started with {product}',
  'requestAccess.byAdmin':
    "Access to {product} is arranged by your organisation's administrator rather than online. If you are the administrator, get in touch with whoever runs {product} for your organisation.",
  'requestAccess.withContact':
    'Accounts for {product} are set up with you rather than on your own. Tell us a little about your organisation and we will get you running.',
  'requestAccess.button': 'Request access',
  'requestAccess.subject': 'Access to {product}',

  'invitation.heading': '{product} is invitation only',
  'invitation.description':
    'New organisations join {product} by invitation. If somebody has invited you, the link in your email is the way in — this page cannot create the account for you.',
  'invitation.ask': 'Ask about an invitation',
  'invitation.byAdmin': "Invitations are issued by your organisation's administrator.",
  'invitation.subject': 'Invitation to {product}',

  'verify.title': 'Confirm your email',
  'verify.incomplete.title': 'That link is incomplete',
  'verify.incomplete.description': 'Open the link from your email again, or start over.',
  'verify.incomplete.startOver': 'Start over',
  'verify.rateLimited.title': 'Too many attempts',
  'verify.rateLimited.description':
    'Your link is still good. Wait a few minutes and open it again — do not start over, that will not help.',
  'verify.invalid.title': 'That link is not valid',
  'verify.invalid.description':
    'It may have been used already, or it may have expired. Sign up again to get a new one.',
  'verify.invalid.again': 'Sign up again',

  // ── /activate: the owner's first password, from the welcome email ──────────
  // Failure wording keeps the verify page's property: one message for every
  // bad link, in every language. See that page for why.
  'activate.title': 'Set your password',
  'activate.heading': 'Welcome to {product}',
  'activate.description':
    'Set a password for {email} to finish setting up {organization}.',
  'activate.form.password': 'Password',
  'activate.form.hint': 'At least 8 characters. Your organisation may require more.',
  'activate.form.confirm': 'Confirm password',
  'activate.form.tooShort': 'Use at least 8 characters.',
  'activate.form.mismatch': 'The two passwords do not match.',
  'activate.form.submit': 'Set password and continue',
  'activate.form.submitting': 'Setting your password…',
  'activate.done.title': 'Your password is set',
  'activate.done.description': 'Sign in with your email address and the password you just chose.',
  'activate.done.signIn': 'Sign in',
  'activate.incomplete.title': 'That link is incomplete',
  'activate.incomplete.description': 'Open the link from your welcome email again.',
  'activate.rateLimited.title': 'Too many attempts',
  'activate.rateLimited.description': 'Wait a few minutes and open the link again. Nothing was lost.',
  'activate.invalid.title': 'That link is not valid',
  'activate.invalid.description':
    'It may have been used already or expired. If you have set a password, sign in; otherwise use “Forgot password” on the sign-in page.',
  'activate.failed': 'Something went wrong on our side. Wait a moment and try again.',

  'provisioning.ready.title': 'Your workspace is ready',
  'provisioning.ready.description': 'Taking you to {product} to sign in.',
  'provisioning.ready.redirecting': 'Redirecting…',
  'provisioning.ready.continue': 'Continue to sign in',
  'provisioning.failed.title': 'We could not finish setting up your workspace',
  'provisioning.failed.description':
    'Your email is confirmed and nothing is lost. Someone needs to look at this before you can sign in.',
  'provisioning.failed.descriptionContact':
    'Your email is confirmed and nothing is lost. Someone needs to look at this before you can sign in, and we would like to hear from you.',
  'provisioning.failed.getInTouch': 'Get in touch',
  'provisioning.failed.subject': 'Setting up {product}',
  'provisioning.slow.title': 'This is taking longer than usual',
  'provisioning.slow.description':
    'Your account is still being set up. We will email you the moment it is ready — you can close this page.',
  'provisioning.waiting.title': 'Setting up your workspace',
  'provisioning.waiting.description':
    'We are creating <strong>{slug}</strong> in {product}. This usually takes a minute or two.',
  'provisioning.waiting.descriptionNoSlug':
    'We are creating your workspace in {product}. This usually takes a minute or two.',
  'provisioning.waiting.status':
    'Setting up your organisation, your account and your workspace.',
  'provisioning.waiting.close': 'You can close this page — we will email you when it is ready.',

  'notFound.title': 'We cannot find that page',
  'notFound.description': 'The link may be out of date, or the page may have moved.',
  'notFound.home': 'Go to the homepage',

  /* ------------------------------------------------------------ dashboard */
  'dashboard.welcome': 'Welcome to {product}',
  'dashboard.intro':
    'You are signed in. This is the starting point for {product}; the first screen your team builds replaces this one.',
  'dashboard.start.title': 'Where to start',
  'dashboard.start.build':
    "Build this page in <code>apps/web/src/app/dashboard</code>. Everything you add beside it is protected by default, sits inside the product shell, and inherits this customer's branding.",
  'dashboard.start.sidebar':
    'Give a new area a place in the sidebar by adding a module to <code>navigation</code> in <code>packages/branding/src/index.ts</code>. Nothing in the shell changes; the same entry is what guards the route.',
  'dashboard.start.config':
    "The public site, its content, this product's own colours and the languages it offers are configured in the same file.",
  'dashboard.start.branding':
    "A customer's own colours arrive through <code>apps/web/src/lib/tenant-branding.ts</code>, read from what they set in the platform's portal and layered over this product's own tenant settings.",

  'insights.title': 'Insights',
  'insights.notInPlan': 'Insights is not part of your plan. Speak to us about adding it.',

  /* ------------------------------------------------------------ analytics */
  'analytics.title': 'Analytics',
  'analytics.unresolved':
    "Your plan could not be read from the KORAS platform just now, so only the reports every plan includes are shown. The reason is in this deployment's server log.",
  'analytics.notIncluded.title': 'Not included in your plan',
  'analytics.notIncluded.description':
    'Analytics is part of a higher plan. Your current plan is <strong>{plan}</strong>. An administrator of your organisation can change the plan in the account portal.',
  'analytics.notIncluded.notRecorded': 'not recorded',
  'analytics.of': '{used} of {limit}',
  'analytics.previousPeriod': 'vs the previous period',
  'analytics.trend.up': 'Up',
  'analytics.trend.down': 'Down',
  'analytics.trend.unchanged': 'Unchanged',
  'analytics.kind.estimated': 'Estimated',
  'analytics.kind.derived': 'Derived',
  'analytics.kind.unavailable': 'Not available',
  'analytics.chart.asTable': 'Show as a table',
  'analytics.chart.noData': 'Nothing in this period.',
  'analytics.chart.value': 'Value',
  'analytics.chart.period': 'Period',
  'analytics.table.empty': 'Nothing to show for this period.',
  'analytics.table.truncated':
    'Only the first rows are shown. Narrow the period to see everything.',
  'analytics.filters.period': 'Period',
  'analytics.filters.from': 'From',
  'analytics.filters.to': 'To',
  'analytics.filters.apply': 'Apply',
  'analytics.export.download': 'Download',
  'analytics.export.notAllowed': 'Downloading is not included in your plan or your role.',
  'analytics.export.background': 'Prepare in the background',
  'analytics.export.queued':
    'The file is being prepared. It will appear under Exports below when it is ready.',
  'analytics.export.csv': 'CSV',
  'analytics.export.xlsx': 'Excel',
  'analytics.export.pdf': 'PDF',
  'analytics.schedule.heading': 'Scheduled delivery',
  'analytics.schedule.intro':
    'Have this report sent by email on a schedule. Each delivery covers the previous day, week or month.',
  'analytics.schedule.cadence': 'How often',
  'analytics.schedule.daily': 'Every day',
  'analytics.schedule.weekly': 'Every week',
  'analytics.schedule.monthly': 'Every month',
  'analytics.schedule.format': 'Format',
  'analytics.schedule.recipients': 'Send to',
  'analytics.schedule.recipientsHint': 'Email addresses, separated by commas. Up to ten.',
  'analytics.schedule.create': 'Schedule',
  'analytics.schedule.remove': 'Remove',
  'analytics.schedule.empty': 'Nothing is scheduled for this report.',
  'analytics.schedule.next': 'Next delivery',
  'analytics.schedule.notIncluded': 'Scheduled delivery is not included in your plan.',
  'analytics.schedule.created': 'The schedule was created.',
  'analytics.schedule.removed': 'The schedule was removed.',
  'analytics.schedule.invalid': 'The schedule could not be created. Check the addresses and try again.',
  'analytics.exports.heading': 'Exports',
  'analytics.exports.intro': 'Files prepared in the background, ready to download.',
  'analytics.exports.empty': 'No exports yet.',
  'analytics.exports.download': 'Download',
  'analytics.exports.pending': 'Preparing…',
  'analytics.exports.failed': 'The file could not be prepared.',
  'analytics.exports.retention': 'Exports are kept for {days} days.',
  'analytics.exports.gone': 'That export is no longer available.',
  'analytics.error.format': 'That format is not offered for this report.',
  'analytics.list.heading': 'Reports',
  'analytics.category.overview': 'Overview',
  'analytics.category.usage': 'Usage',
  'analytics.category.people': 'People',
  'analytics.category.billing': 'Billing',
  'analytics.category.ai': 'AI',
  'analytics.category.activity': 'Activity',
  'analytics.category.product': 'This product',
  'analytics.loading': 'Loading the report…',
  'analytics.retry': 'Try again',
  'analytics.error.plan': 'Your plan does not include this report.',
  'analytics.error.forbidden': 'Your account may not open this report.',
  'analytics.error.filters': 'Those filters are not ones this report accepts.',
  'analytics.error.export': 'Your plan does not include downloading reports.',
  'analytics.error.unavailable':
    'Analytics is not available right now. The reason is in the server log.',
  'analytics.error.generic': 'Something went wrong. Try again.',

  /* ------------------------------------------------------------- settings */
  'settings.title': 'Settings',
  'settings.intro':
    "What {product} is, what this deployment contains, and what your organisation's plan includes.",
  'settings.product.title': 'Product',
  'settings.product.name': 'Name',
  'settings.product.identifier': 'Identifier',
  'settings.product.tagline': 'Tagline',
  'settings.product.configuredIn':
    "Configured in <code>packages/branding/src/index.ts</code>, which is also where this product's colours, logo, languages and sidebar modules are declared.",
  'settings.deployment.title': 'This deployment',
  'settings.deployment.description':
    'The components this repository was generated with. A sidebar module requiring one that is absent is hidden rather than broken, and the list is fixed for the life of the repository — adding one means generating with it.',
  'settings.plan.title': 'Plan',
  'settings.plan.resolved': 'Resolved from the KORAS platform for your organisation.',
  'settings.plan.plan': 'Plan',
  'settings.plan.features': 'Included features',
  'settings.plan.noneRecorded': 'None recorded',
  'settings.plan.unavailable':
    "Not available. Your plan could not be read from the KORAS platform just now, so anything gated by plan is unavailable until it can be. Nothing else about the product is affected, and the reason is in this deployment's server log.",
  'settings.plan.portalHint':
    'Subscriptions and billing are managed in the KORAS account portal. Set <code>product.accountUrl</code> to link to it from here and from the profile menu.',
  'settings.plan.manage': '<a>Manage your subscription</a> in the KORAS account portal.',
  'settings.language.title': 'Language',
  'settings.language.description':
    'The language {product} is shown to you in, on this device. It applies to the interface only; what your organisation puts into the product stays as it was entered.',
  'settings.language.label': 'Show {product} in',
  'settings.language.save': 'Change language',
  'settings.appearance.title': 'Appearance',
  'settings.appearance.description':
    'Light, dark, or whatever this device is set to. Remembered in this browser only.',

  /* ---------------------------------------------------------------- files */
  'files.title': 'Files',
  'files.intro':
    'What your organisation has stored in {product}. Files go straight from your browser to the storage your organisation has been assigned; the product keeps the list.',
  'files.unresolved':
    'Your plan could not be read from the KORAS platform just now, so no storage limit is shown. Uploads still work.',
  'files.notIncluded.title': 'Not included in your plan',
  'files.notIncluded.description':
    'File storage is part of a higher plan. Your current plan is <strong>{plan}</strong>. What is already stored stays.',
  'files.notIncluded.notRecorded': 'not recorded',
  'files.upload': 'Upload a file',
  'files.uploading': 'Uploading…',
  'files.choose': 'Choose a file to upload',
  'files.download': 'Download',
  'files.remove': 'Delete',
  'files.confirmRemove': 'Delete {name}? This cannot be undone.',
  'files.empty': 'Nothing stored yet',
  'files.emptyHint': 'Upload a file and it will appear here for everyone in your organisation.',
  'files.column.name': 'Name',
  'files.column.size': 'Size',
  'files.column.uploadedAt': 'Uploaded',
  'files.column.searchable': 'Assistant',
  'files.searchable.yes': 'Searchable',
  'files.searchable.pending': 'Indexing…',
  'files.searchable.no': 'Not searchable',
  'files.usage': '{used} of {limit} used',
  'files.usageUnlimited': '{used} used',
  'files.usageUnknown': 'Usage limit not available right now',
  'files.provider': 'Stored with {provider}',
  'files.retry': 'Try again',
  'files.error.plan': 'Your plan does not include this, or the upload would exceed its storage limit.',
  'files.error.forbidden': 'Your account may not do that.',
  'files.error.notArrived': 'The file did not arrive in storage as expected. Try the upload again.',
  'files.error.unavailable':
    'File storage is not available for your organisation right now. The reason is in the server log.',
  'files.error.generic': 'Something went wrong. Try again.',

  /* --------------------------------------------------------------- assistant */
  'assistant.title': 'Assistant',
  'assistant.intro':
    'Ask about what you are working on. The assistant can read what your organisation holds and can propose actions, which run only after somebody approves them.',
  'assistant.unresolved':
    'Your plan could not be read just now, so the assistant may refuse. If it keeps happening, tell an administrator.',
  'assistant.notIncluded.title': 'Not included in your plan',
  'assistant.notIncluded.description':
    'The assistant is not part of the <strong>{plan}</strong> plan. An administrator of your organisation can change the plan in the account portal.',
  'assistant.notIncluded.notRecorded': 'not recorded',
  'assistant.open': 'Open the assistant',
  'assistant.close': 'Close the assistant',
  'assistant.drawerTitle': 'Assistant',
  'assistant.newConversation': 'New conversation',
  'assistant.empty': 'Ask anything about your organisation',
  'assistant.emptyHint': 'The assistant answers from what your organisation holds here, and nothing else.',
  'assistant.you': 'You',
  'assistant.speaker': 'Assistant',
  'assistant.composer.label': 'Your message',
  'assistant.composer.placeholder': 'Ask the assistant…',
  'assistant.send': 'Send',
  'assistant.sending': 'Thinking…',
  'assistant.retry': 'Try again',
  'assistant.suggestions.title': 'Try asking',
  'assistant.suggestions.files': 'What files do we have?',
  'assistant.suggestions.summary': 'Summarise what I am looking at',
  'assistant.usage': '{used} of {limit} requests used this month',
  'assistant.usageUnlimited': '{used} requests this month',
  'assistant.usageOverage':
    '{used} requests this month, beyond your plan\'s {limit}. Pay-as-you-go charges so far: ${charges}',
  'assistant.usageUnknown': 'Usage allowance not available right now',
  'assistant.citations': 'Sources',
  'assistant.activity.title': 'Recent assistant activity',
  'assistant.activity.hint': 'What the assistant proposed, ran, was refused and was decided, for the people who approve. Never the content of a conversation.',
  'assistant.activity.empty': 'Nothing recorded yet.',
  'assistant.pending.title': 'Waiting for approval',
  'assistant.pending.hint':
    'The assistant proposed this and it will not run until somebody approves it.',
  'assistant.pending.cannotDecide': 'An administrator of your organisation has to decide this.',
  'assistant.approve': 'Approve',
  'assistant.reject': 'Reject',
  'assistant.deciding': 'Working…',
  'assistant.operation.read': 'Reads',
  'assistant.operation.write': 'Changes something',
  'assistant.operation.destructive': 'Deletes something',
  'assistant.operation.external': 'Leaves the product',
  'assistant.toolResult': 'Result from {tool}',
  'assistant.toolResultShow': 'Show the details',
  'assistant.error.plan': 'Your plan does not include the assistant.',
  'assistant.error.forbidden': 'Your account may not do that.',
  'assistant.error.limit': 'Your organisation has used its assistant allowance for this month.',
  'assistant.error.unavailable':
    'The assistant is not available right now. The reason is in the server log.',
  'assistant.error.timeout': 'The assistant took too long to answer. Try again.',
  'assistant.error.generic': 'Something went wrong. Try again.',

  /* --------------------------------------------------------- team & access */
  'team.title': 'Team & Access',
  'team.intro':
    'Who in your organisation may use {product}, and what they may do here. Adding and removing people from the organisation itself is done in the KORAS account portal; this page governs access to this product only.',
  'team.yours.title': 'Your access',
  'team.yours.signedInAs': 'Signed in as',
  'team.yours.role': 'Role in this product',
  'team.yours.orgRoles': 'Organisation roles',
  'team.yours.permissions': 'Permissions',
  'team.how.title': 'How access is decided',
  'team.how.description':
    'Each organisation role carries a set of permissions in this product. The mapping lives in <code>packages/permissions/src/index.ts</code> and is the same one the sidebar and every route check read — a module hidden from the navigation is refused at its URL by the same rule, not merely left out of the menu.',
  'team.how.caption': 'Organisation roles and the product permissions each carries',
  'team.how.colRole': 'Organisation role',
  'team.how.colPermissions': 'Permissions in this product',
  'team.perPerson.title': 'Per-person assignment',
  'team.perPerson.description':
    "Not available yet. Access to this product is currently derived from each person's organisation role, so everyone with a role in your organisation can open {product}. Granting or revoking one person's access to this product independently needs an assignment store this repository does not have; <code>packages/permissions/src/index.ts</code> names the single function that changes when it arrives.",
  'team.perPerson.manage':
    'You hold <code>team.manage</code>, so the controls for it will appear here for you once they exist.',

  /* ----------------------------------------------------- legal page frame */
  'legal.notReviewed.label': 'Not yet reviewed.',
  'legal.notReviewed.text':
    'This page describes what the software does. It is not a legal document and has not been checked by anyone qualified to write one. Replace it before this product is sold, and pass <code>reviewed</code> to remove this notice.',

  /* -------------------------------------------------------------- privacy */
  'privacy.title': 'Privacy',
  'privacy.metaDescription': 'How {product} handles personal data.',
  'privacy.summary': 'What {product} stores about the people who use it, and why.',
  'privacy.stored.title': 'What is stored about you',
  'privacy.stored.p1':
    "When you sign in, {product} records the identifier your organisation's sign-in provider gives us, your email address and your display name. It records which organisation you belong to and what role you hold there, because those two facts decide what you are allowed to open.",
  'privacy.stored.p2':
    'Anything else in {product} is data your own organisation put there. It belongs to them, not to us.',
  'privacy.who.title': 'Who can see it',
  'privacy.who.p1':
    "Your organisation's data is separated from every other organisation's in the database itself, by row-level security, rather than by a filter in the application. A query that forgets to scope itself returns nothing rather than somebody else's records.",
  'privacy.who.p2':
    'People who administer {product} can reach data in the course of running and supporting it. What they do is recorded.',
  'privacy.signin.title': 'Sign-in',
  'privacy.signin.p1':
    "{product} never sees your password. Sign-in happens at your organisation's identity provider, which tells us only who you are and what you may do. Your session is a cookie this application signs, readable by nobody else and sent only to this site.",
  'privacy.cookies.title': 'Cookies',
  'privacy.cookies.p1':
    'Three, and all are necessary: one holds your session, one carries the token this application forwards to its own API, and one remembers the language you chose. There is no advertising or analytics cookie in {product} as it is shipped.',
  'privacy.ask.title': 'Asking us about your data',
  'privacy.ask.contactAdmin': 'Contact whoever administers {product} in your organisation.',
  'privacy.ask.writeTo': 'Write to <a>{email}</a>.',

  /* ---------------------------------------------------------------- terms */
  'terms.title': 'Terms',
  'terms.metaDescription': 'The terms on which {product} is provided.',
  'terms.summary': 'What you can expect from {product}, and what it expects from you.',
  'terms.accounts.title': 'Accounts',
  'terms.accounts.p1':
    'Access to {product} belongs to an organisation, not to a person. Your organisation decides who may sign in and what each person may do; removing somebody from the organisation removes their access.',
  'terms.accounts.p2':
    'You are responsible for what happens under your sign-in. Tell your administrator promptly if you think somebody else is using it.',
  'terms.plans.title': 'Plans',
  'terms.plans.p1':
    'What your organisation may use is decided by its plan. Features outside it are either hidden or shown as unavailable — never silently degraded, and never charged for without being bought.',
  'terms.plans.p2':
    'A trial ends on its date. When it does, access to plan-gated features stops and the account itself stays open, so somebody can still sign in and choose a plan.',
  'terms.data.title': 'Your data',
  'terms.data.p1':
    "The data your organisation puts into {product} remains your organisation's. It is stored separately from every other organisation's, and it is not used to train anything or sold to anybody.",
  'terms.use.title': 'Acceptable use',
  'terms.use.p1':
    "Do not attempt to reach another organisation's data, disrupt the service for others, or use {product} to break the law. Access can be suspended where any of those is happening.",
  'terms.changes.title': 'Changes',
  'terms.changes.p1':
    'These terms can change. Material changes are announced before they take effect, not applied quietly.',

  /* ------------------------------------------------------------------ FAQ */
  'faq.title': 'FAQ',
  'faq.metaDescription': 'Common questions about {product}.',
  'faq.summary': 'The questions {product} is asked most often.',
  'faq.signin.title': 'How do I sign in?',
  'faq.signin.p1':
    "Through your organisation's identity provider. {product} never asks for or stores a password — you are sent to sign in, and you come back here. If your organisation requires a second factor, you will be asked for it and refused without it rather than looped back to the sign-in page.",
  'faq.missing.title': 'Why can I not see a section other people can?',
  'faq.missing.p1': 'Four things decide it, and they fail differently on purpose.',
  'faq.missing.p2':
    "Your <strong>role</strong> decides what you may do; a section you have no permission for is hidden, and its address is refused as well. Your organisation's <strong>plan</strong> decides what it has bought; those sections either do not appear or appear locked, depending on whether it is something you could add. Your organisation's own <strong>feature switches</strong> work the same way. And some sections only exist in builds that were generated with them.",
  'faq.missing.p3':
    'Settings → General names the file behind each of the four, which is the fastest way to find out which one you have hit.',
  'faq.people.title': 'Who can add or remove people?',
  'faq.people.p1':
    'Owners and administrators of your organisation, in the KORAS account portal. Team & Access in {product} shows who has access here and what each role carries; adding somebody to the organisation itself happens in the portal.',
  'faq.trial.title': 'What happens when a trial ends?',
  'faq.trial.p1':
    'Features that need a plan stop being available, and everything else keeps working. The account stays open and you can still sign in — an account that disappeared with the trial would be one nobody could upgrade.',
  'faq.branding.title': 'Can we use our own colours and logo?',
  'faq.branding.p1':
    "Yes. An administrator sets them for your organisation and every signed-in page picks them up — colours, corner radius, and a logo for light and dark backgrounds. The product's own branding is what you see until then.",
  'faq.language.title': 'Can I use {product} in another language?',
  'faq.language.p1':
    'Yes, where the product offers one. The language switcher in the header and in Settings changes the interface for you on this device, and your browser’s own language preference is used until you choose.',
  'faq.isolation.title': "Is my organisation's data separate from everyone else's?",
  'faq.isolation.p1':
    'Yes, and it is separated in the database rather than by the application remembering to ask. A query that does not name your organisation returns nothing at all.',

  // F20 phase 2: persistence and admin
  /* ------------------------------------------------------ language, stored */
  'settings.language.remembered':
    'Because you are signed in, your choice is kept with your account and follows you to every device you sign in on.',
  'settings.language.tenantTitle': 'Default for your organisation',
  'settings.language.tenantDescription':
    'What a member of your organisation sees before they choose a language for themselves. Anyone who has already chosen keeps their choice.',
  'settings.language.tenantLabel': 'Members start in',
  'settings.language.tenantFollowBrowser': 'Their browser’s language',
  'settings.language.tenantSave': 'Save default',
  'settings.language.tenantSaving': 'Saving…',
  'settings.language.tenantSaved': 'The default language was saved.',
  'settings.language.tenantError': 'The default language could not be saved. Try again in a moment.',
  'settings.language.tenantForbidden': 'Only an owner or administrator can change the default language.',

  /* ------------------------------------------------------------- admin */
  'admin.title': '{product} Admin',
  'admin.login.audience':
    'For organization owners and administrators. Multi-factor authentication is required.',
  'admin.mfaRequired': 'Multi-factor authentication is required. Enrol a second factor, then sign in again.',
  'admin.forbidden': 'This application is for organization owners and administrators.',
  'admin.home.signedInAs': 'Signed in as {name}.',

  /* ------------------------------------------ F20 phase 2: errors and email */
  // One sentence per `ApiErrorCode` the API can answer with
  // (services/api/koras_api/core/errors.py). The API's own `message` is for
  // the log and never shown; these are what a person reads. Mapped by
  // `apps/web/src/lib/api-errors.ts`.
  'restore.title':
    'Restore',
  'restore.description':
    'Bringing a file back from its backup. Two people decide: one asks, someone else approves. Nothing is restored until they do.',
  'restore.available':
    'What can be restored',
  'restore.availableDescription':
    'Files with a backup copy. A file that has been deleted still appears here -- that is what the copy is for.',
  'restore.requests':
    'Requests',
  'restore.requestsDescription':
    'Every request and where it has got to. A refused one is kept, because it is the one somebody asks about later.',
  'restore.name':
    'File',
  'restore.copied':
    'Copied',
  'restore.size':
    'Size',
  'restore.state':
    'State',
  'restore.present':
    'Still here',
  'restore.deleted':
    'Deleted',
  'restore.verified':
    'Copy verified',
  'restore.unverified':
    'Copied, not verified',
  'restore.ask':
    'Ask to restore',
  'restore.asking':
    'Asking...',
  'restore.cancel':
    'Cancel',
  'restore.reason':
    'Why this file is needed',
  'restore.reasonHint':
    'Whoever approves this will read it. It is kept with the request.',
  'restore.overwrite':
    'Replace the existing file',
  'restore.overwriteHint':
    'Leave this off and the file comes back as a new copy. Nothing is replaced.',
  'restore.overwriteWarning':
    'The file that is there now will be replaced by the backup. Whoever approves has to confirm this separately.',
  'restore.askNewCopy':
    'Ask for a new copy',
  'restore.askOverwrite':
    'Ask to replace the file',
  'restore.emptyBackups':
    'No file has a backup copy yet. Backups run nightly once a destination is configured.',
  'restore.emptyRequests':
    'No one has asked for a restore.',
  'restore.pending':
    'Already asked for',
  'restore.approve':
    'Approve',
  'restore.approveOverwrite':
    'Approve replacing the file',
  'restore.refuse':
    'Refuse',
  'restore.who':
    'Asked by',
  'restore.yours':
    'You asked for this one, so somebody else approves it.',
  'restore.refresh':
    'Refresh',
  'restore.error.forbidden':
    'You do not have permission to restore files.',
  'restore.error.unavailable':
    'Restores cannot be reached at the moment. Try again shortly.',
  'audit.title':
    'Audit',
  'audit.description':
    'What happened in your organization: who did what, to which record, and how it ended. Records are kept for as long as their kind requires and no longer.',
  'audit.filters':
    'Filters',
  'audit.action':
    'Action',
  'audit.actor':
    'Person',
  'audit.outcome':
    'Result',
  'audit.classification':
    'Kind',
  'audit.any':
    'Any',
  'audit.apply':
    'Search',
  'audit.clear':
    'Clear',
  'audit.searching':
    'Searching…',
  'audit.empty':
    'Nothing has been recorded yet.',
  'audit.emptyFiltered':
    'Nothing matches those filters.',
  'audit.more':
    'Show more',
  'audit.when':
    'When',
  'audit.what':
    'Action',
  'audit.who':
    'Person',
  'audit.target':
    'Record',
  'audit.result':
    'Result',
  'audit.kind':
    'Kind',
  'audit.details':
    'Details',
  'audit.exportTitle':
    'Export',
  'audit.exportDescription':
    'Take a copy of the records matching your filters. The file is prepared in the background and stays available for seven days.',
  'audit.exportFormat':
    'Format',
  'audit.exportStart':
    'Start export',
  'audit.exportPending':
    'Refresh',
  'audit.exportDownload':
    'Download',
  'audit.exportEmpty':
    'No exports yet.',
  'audit.exportRows.one':
    '{rows} record',
  'audit.exportRows.other':
    '{rows} records',
  'audit.restricted':
    'Some kinds of record need an owner or administrator to read.',
  'audit.error.forbidden':
    'You do not have permission to read the audit history.',
  'audit.error.unavailable':
    'The audit history could not be read right now.',
  'errors.tokenInvalid': 'Your session has expired. Sign in again.',
  'errors.tenantInactive': 'Your organisation is not active in this product.',
  'errors.roleRequired': 'Only an owner or administrator of your organisation can do that.',
  'errors.permissionMissing': 'Your role does not include that.',
  'errors.entitlementMissing': 'Your plan does not include this.',
  'errors.storageLimitExceeded': 'This upload would exceed the storage included in your plan.',
  'errors.fileNotFound': 'That file no longer exists.',
  'errors.uploadNotArrived': 'The file did not arrive in storage as expected. Try the upload again.',
  'errors.uploadSizeMismatch':
    'The uploaded file is not the size that was announced. Try the upload again.',
  'errors.backupNotFound':
    'No backup of this file exists, so there is nothing to restore it from.',
  'errors.restoreNotFound':
    'No such restore request.',
  'errors.restoreNotTransitionable':
    'This restore request has already been decided.',
  'errors.restoreAlreadyRequested':
    'A restore of this file is already waiting to be decided.',
  'errors.restoreOverwriteUnconfirmed':
    'This request replaces the existing file. Approve it saying so, or ask for a new copy instead.',
  'errors.fileUnderHold':
    'This file cannot be deleted: a legal hold is keeping it. It can be deleted once the hold is lifted.',
  'errors.fileQuarantined':
    'This file is being withheld because a security scan did not find it clean. Ask an administrator if you need it.',
  'errors.holdNotFound':
    'That legal hold does not exist.',
  'errors.holdNotTransitionable':
    'That legal hold has already been decided; reload the list to see its current state.',
  'errors.holdInvalidWindow':
    'A legal hold cannot end before it starts.',
  'errors.auditEventNotFound':
    'That audit event does not exist.',
  'errors.storageUnavailable': 'File storage is not available right now.',
  'errors.reportNotFound': 'That report does not exist.',
  'errors.scheduleNotFound': 'That schedule no longer exists.',
  'errors.exportNotFound': 'That export no longer exists.',
  'errors.exportFormatUnknown': 'That export format is not recognised.',
  'errors.exportFormatUnsupported': 'This report cannot be exported in that format.',
  'errors.filterInvalid': 'One of the filters is not valid for this report.',
  'errors.recipientInvalid': 'One of the recipients is not an email address.',
  'errors.periodNotAFilter': 'The period of a scheduled report is decided by its cadence.',
  'errors.reportFailed': 'The report could not be produced. Try again later.',
  'errors.toolDenied': 'Your role does not allow that in the assistant.',
} as const
