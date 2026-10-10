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
   `http://zitadel:8080`, a host that matches no instance. Without it `/healthy`
   answers and every sign-in page fails; that is integration case T-I13.
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
