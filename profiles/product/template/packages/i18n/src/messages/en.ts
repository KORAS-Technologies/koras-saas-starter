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
  'shell.lockedFeature': 'Not enabled for your organisation',
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
  'login.note':
    'Signing in uses your organisation account. There is no separate {product} password to remember or reset.',

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
  'signup.form.submit': 'Create account',
  'signup.form.submitting': 'Creating your account',
  'signup.form.note':
    'We will email you a link to confirm the address. Nothing is created until you open it.',
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

  'reports.title': 'Reports',
  'reports.notIncluded.title': 'Not included in your plan',
  'reports.notIncluded.description':
    'Advanced reporting is part of a higher plan. Your current plan is <strong>{plan}</strong>.',
  'reports.notIncluded.notRecorded': 'not recorded',
  'reports.unresolved':
    "Your plan could not be read from the KORAS platform just now, so this may be available to you. The reason is in this deployment's server log.",
  'reports.included':
    'Included in your plan. Build the real thing here — this page exists so the plan gate has somewhere to lead, and so the pattern is visible before anyone needs it.',

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
} as const
