# The product's own sign-in

> Scope: how a customer signs in to a generated product without seeing a
> ZITADEL page, what each side does, what it deliberately does not do yet,
> and how to turn it on for an estate. Built 2026-09-11. The Control Plane
> half is `koras-control-plane/services/api/koras_api/routers/sign_in.py`;
> its design record is `koras-control-plane/docs/SECURITY_MODEL.md` §8 and
> R-90 there.

## The claim

Before this, every customer of every product signed in on ZITADEL Cloud's
hosted login page -- "Welcome back!", Lato, a language dropdown -- because
the product's `/login` button sends the browser to ZITADEL's authorize
endpoint, and ZITADEL renders its own page to anyone without a session
there. `SECURITY_MODEL` §8 in the Control Plane says customers never see
that page; R-90 records that they always did.

Now the sign-in page is the product's. The same button starts the same OIDC
flow; ZITADEL, told per application that this product hosts its own login,
sends the browser straight back to `/login?authRequest=…` instead of
rendering anything; the product's form posts the email address, the password
and that id to the Control Plane from its server; the platform checks them
with ZITADEL's session API, asks whether a second factor is enrolled, and
finalises the auth request; the browser is sent to the callback URL and
lands on the product's `/api/auth/callback` with an authorization code,
exactly as it would have from ZITADEL's page. The callback route, the
cookies it checks and the session it mints are unchanged.

A customer sees the product's page, then the product. The flow, in one line
per hop:

```text
/login  ──click──▶  /api/auth/start  ──302──▶  ZITADEL /oauth/v2/authorize
   ▲                                                      │  (login_version = v2, base_uri = <product>/login)
   └──────────── 302 /login?authRequest=V2_…  ◀───────────┘
/login form ──POST (server action)──▶  Control Plane  POST /api/sign-in/v1/attempts
                                            │  POST /v2/sessions (user + password, checked together)
                                            │  GET  /v2/users/{id}/authentication_methods
                                            │  POST /v2/oidc/auth_requests/{id}  ──▶ callbackUrl
/login  ──302 callbackUrl──▶  ZITADEL  ──302──▶  /api/auth/callback?code=…&state=…  (as before)
```

Where the person has a TOTP factor enrolled, the platform answers
`factor_required` with an attempt id instead of a callback URL, the form
asks for the code, and a second post to `/attempts/{id}/factor` finishes
the same way.

## What each side holds, and what it does not

**The product** holds no ZITADEL credential and no session token. It holds
`KORAS_CONTROL_PLANE_URL`, which it already had for signup and activation,
and it carries two ids through hidden fields: ZITADEL's auth request id,
which authorises nothing without the password, and the platform's attempt
id, which authorises nothing without the code. The password is read into
one request body and nowhere else. `apps/web/src/app/login/actions.ts`
checks the callback URL it is handed against `ZITADEL_DOMAIN` before
redirecting to it, so a platform answering something else cannot turn the
sign-in into a redirect anywhere.

**The Control Plane** holds the ZITADEL service token it already held for
activation, and the half-done sign-ins: a table of sign-in attempts
(migration 00036) keeps the session id and token ZITADEL issued after the password
check, for ten minutes and one use, so that the product never carries a
session credential. It honours an auth request only when its client id is a
registered product's in that environment -- without that, the route would
sign a password holder into any application on the instance, the Console
included.

**ZITADEL** is told per application. `login_version { login_v2 { base_uri } }`
on the product's OIDC application, set by `infrastructure/terraform/modules/zitadel`
from the `web-<env>` domain the Vercel module created, moves exactly one
application's sign-in. The value is the origin: ZITADEL appends
`/login?authRequest=…` itself. The instance-wide Login V2 feature flag would
have moved the Console and every other application on the instance too,
staff included, which is why the earlier plan to self-host ZITADEL's login
app (F23, `koras-control-plane/docs/LOGIN_UI_PLAN.md`) needed a break-glass
token and a week on dev. This needs neither: an environment whose
`login_base_uri` is null keeps the hosted login, and the product's page is
the button it always was.

One instance-level fact the first live run found (2026-09-11): ZITADEL Cloud
creates an instance with the feature "Login V2 required" **on**, and while
it is on, ZITADEL overwrites every application's own login setting with the
instance's (`internal/query/oidc_client.go`), so the per-application URL is
silently ignored and the browser lands on the hosted page as before. The
feature has to be off for the per-application setting to count. Turning it
off moves nothing by itself: every KORAS application declares the V2 login
explicitly, with or without a base URI, so the Console is the only
application left to ZITADEL's default, and on these instances that default
still answers.

## One answer for every refusal

A wrong password, an address nobody has, a locked account and a disabled
one are one 401 from the platform and one sentence on the page. Which it
was goes to the platform's log as ZITADEL's error identifier
(`Errors.User.Password.Invalid`), never with the login name attached. The
page must not guess between them, and the test that would fail if it did is
`e2e/sign-in.spec.ts` in the generated project.

A forgotten password is the mechanism the portal already had: the platform
finds which organizations the address belongs to on this product and has
the worker send each one this platform's own email, whose link opens
`/activate` here and sets the password server-side (Control Plane R-107).
The platform answers 202 whether the address matched nothing or several
organizations, and `/login/forgot` says the same thing either way.

Budgets: twenty password or code checks in ten minutes from one address,
five reset mails an hour. ZITADEL's own lockout policy is the second line,
per account rather than per address.

## What is deliberately not in it

- **Only TOTP as a second factor.** Passkeys and U2F need a browser
  ceremony the platform cannot take part in; OTP by mail or SMS would have
  ZITADEL send its own message, which R-107 forbids. A person whose only
  second factor is one of those is signed in on the password, and the
  product's middleware refuses the session if their organization requires
  a second factor -- the refusal they would meet today. Nobody has any of
  them enrolled: no product has offered enrolment yet, which is the other
  half of R-90 and stays open.
- **No "keep me signed in".** ZITADEL's own login remembered its session in
  a cookie on ZITADEL's host, so a second sign-in within its lifetime asked
  for nothing. Here every sign-in asks for the password. The product's own
  session lasts as long as the ID token, as before; what changed is what
  happens when it ends. Reusing a held ZITADEL session would mean the
  platform keeping session tokens past one use, and is not done until a
  customer asks.
- **The Control Plane's portal and the product's admin application** still
  sign in on ZITADEL's page. The portal is the Control Plane's to change;
  the admin application is staff-only, which §8 does not cover.
- **Enrolment** of a second factor on a product page. R-90's enrolment
  half; not started.
- **The local stack.** `local/zitadel/provision.py` leaves the local OIDC
  application on the hosted login, because a local product has no Control
  Plane to post to. Locally the page is the button.

## Turning it on for an estate

Two things. `login_base_uri` is derived from the `web-<env>` Vercel domain
in `infrastructure/terraform/modules/project-bootstrap`, so the next
`terraform plan` for a product estate shows one change per environment on
`zitadel_application_oidc.web` -- the `login_version` block -- and nothing
else. Apply it. The provider needs to be 2.4 or later; `koras-e2e-shop`
locks 2.12.8.

Then, once per instance, turn the "Login V2 required" feature off, with a
token that holds `IAM_OWNER` (the worker's service token does):

```text
PUT https://<instance>/v2/features/instance
{"loginV2": {"required": false}}
```

Reverting is the same call with `true`. Done on dev on 2026-09-11; test,
staging and prod still have it on, so their applications keep the hosted
page until somebody makes that call -- which is the right order, since
their web applications are not deployed with the page yet.

Reverting is removing the block, which the null default does: a product
that must go back to the hosted login sets `login_base_uri = null` on the
module call for that environment and applies.

Applied to `koras-e2e-shop`'s dev on 2026-09-11, with the instance feature
turned off the same day: ZITADEL answers the authorize request with a
redirect to the product's `/login?authRequest=…`, and the platform's route
answers the form. A sign-in with a real password has still not been watched
in a browser by a person; the Control Plane's `koras-control-plane/tests/integration/test_product_sign_in.py`
covers what the API does between the two, and the generated project's
`e2e/sign-in.spec.ts` covers the page without a platform behind it.

## Where things are

| What | Where |
| ---- | ----- |
| The page, both shapes | `profiles/product/template/apps/web/src/app/login/page.tsx.hbs` |
| The form and the code step | `profiles/product/template/apps/web/src/app/login/SignInForm.tsx.hbs` |
| The server actions | `profiles/product/template/apps/web/src/app/login/actions.ts.hbs` |
| Forgotten password | `profiles/product/template/apps/web/src/app/login/forgot/` |
| The strings, three languages | `profiles/product/template/packages/i18n/src/messages/` |
| The browser tests | `profiles/product/template/e2e/sign-in.spec.ts.hbs` |
| The per-application setting | `infrastructure/terraform/modules/zitadel/main.tf` |
| Where the URL comes from | `infrastructure/terraform/modules/project-bootstrap/main.tf` |
| The platform's routes | `koras-control-plane/services/api/koras_api/routers/sign_in.py` |
| The platform's ZITADEL calls | `koras-control-plane/services/api/koras_api/core/zitadel_sessions.py` |
| The held attempts | `koras-control-plane/supabase/migrations/00036_sign_in_attempts.sql` |
