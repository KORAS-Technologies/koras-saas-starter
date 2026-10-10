# ADR 0016 — Local sign-in through ZITADEL's login v2, on its own port

**Status.** Accepted for Stage 4.3A, 2026-10-09: decision A7 of the Phase 4.3
specification (v2). New instances only.

**Context.** ZITADEL v4.17.1 defaults `DefaultInstance.Features.LoginV2.Required`
to true, and the Starter shipped no login container, so a local sign-in ended
at a 404 (GR-281). The official compose puts a proxy in front of the API and
the login so both share one origin. The Starter has no proxy in front of
ZITADEL, and adding one was not approved for this stage.

**Decision.**

1. A `zitadel-login` service, `ghcr.io/zitadel/zitadel-login` at the same tag
   as `zitadel` (`v4.17.1`), on `127.0.0.1:${KORAS_PORT_ZITADEL_LOGIN}`, reading
   its token from `/zitadel/bootstrap/login-client.pat`. ZITADEL creates that
   machine user, `login-client`, with IAM_LOGIN_CLIENT, at first start.
2. Because the login is a different origin from the issuer, every login URL is
   absolute: `ZITADEL_DEFAULTINSTANCE_FEATURES_LOGINV2_BASEURI`,
   `ZITADEL_OIDC_DEFAULTLOGINURLV2`, `ZITADEL_OIDC_DEFAULTLOGOUTURLV2` and
   `ZITADEL_SAML_DEFAULTLOGINURLV2` all name `http://localhost:<login port>`.
   v4.17.1's defaults are relative and work only on one origin.
3. `CUSTOM_REQUEST_HEADERS: Host:localhost,X-Forwarded-Proto:http`. ZITADEL
   resolves an instance from the Host header, and the login reaches the API as
   `http://zitadel:8080`, a host that matches no instance. The header names
   the public one.

   **Amended 2026-10-10.** This point said that without the header `/healthy`
   answers and every sign-in page fails, and the specification's T-I13 asserted
   exactly that. CI disproved it on its first run (run 38020999862): on v4.17.1,
   in this layout with no proxy, a browser sign-in through the login works
   either way. The upstream source at `v4.17.1` explains why. The login's
   `getInstanceHost`, in
   `zitadel/zitadel/apps/login/src/lib/server/host.ts`, reads the incoming
   request's `Host`, which is `localhost:<login port>` for a browser here.
   The transport interceptor in
   `zitadel/zitadel/apps/login/src/lib/zitadel.ts` sends it to the API as
   `x-zitadel-instance-host`, and ZITADEL resolves the instance from that
   header. The same interceptor applies `CUSTOM_REQUEST_HEADERS`
   (`zitadel/zitadel/apps/login/src/lib/custom-headers.ts`).

   The header is kept, by owner decision on 2026-10-10, for three reasons. It
   is what ZITADEL's own compose file,
   `zitadel/zitadel/deploy/compose/docker-compose.yml`, sets at `v4.17.1`:
   `Host:${ZITADEL_DOMAIN},X-Forwarded-Proto:${ZITADEL_PUBLIC_SCHEME}`. A call
   the login makes without a browser request behind it has no instance host
   to forward. And without the header, sign-in would depend on the
   instance-host forwarding, which is internal behaviour, rather than on
   configuration.

   T-I13 now asserts what the header does, not what was assumed about it.
   On the running containers it checks three things: the login is
   `zitadel-login:v4.17.1`, matching the state's `zitadelVersion`, and carries
   exactly this header; from inside the login container, `zitadel:8080`
   answers an error and not this instance without the header; and with the
   header, parsed from the container's own environment, the same token
   resolves the recorded instance ID. The case fails on any other version, so
   a version bump has to establish the behaviour again before it can pass.
   It does not claim that a browser sign-in needs the header. Nor does it
   watch the login apply the header. The probe parses the variable itself,
   with the rule `custom-headers.ts` uses at `v4.17.1` (split on commas, then
   on the first colon), so it proves that the configured value names this
   instance, and not that every call the login makes carries it. No case
   exercises a login call made without a browser behind it.
4. `provision.py` sets `loginVersion.loginV2.baseUri` on the application, and
   registers the `https://*.localhost` redirect URIs `.env.local.example`
   names as well as the `http://localhost:<port>` ones.
5. The login port is a new preference, `zitadel_login` (product 8081, Control
   Plane 8084; never 8082, which SQL Server Reporting Services reserves),
   resolved by `ports.sh` and recorded in the state file under the same rule
   as the issuer: a moved port is a refusal, not a walk. The port registry
   (A8) takes this over.
6. Legacy instances are never switched. `LOGINV2_*` defaults apply only to
   instances created afterwards; the legacy override drops the login service
   and every login-v2 setting, and `provision.py` sets no login version on a
   legacy instance.

**Consequences.** The sign-in page is on a different origin from the issuer,
which is supported through the absolute URLs above and is not the layout
ZITADEL's own reference uses. Revisiting a single-origin proxy layout is open
item 7 of the specification, deferred to A8 on 2026-10-09.
