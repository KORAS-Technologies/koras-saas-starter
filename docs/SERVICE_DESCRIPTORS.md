# Service descriptors

> Scope: `services/<service>/service.yaml` — the one file in which a deployable
> service says **which environments it runs in**, **which secrets it may hold**
> and **whether it is reachable from outside**. Shipped 2026-10-03 with the
> optional clamd service ([`CLAMD_SERVICE.md`](CLAMD_SERVICE.md)), which is its
> first and so far only user.

## The rule that matters

A descriptor is **optional and absent by default.** A service with no
`service.yaml` behaves exactly as services behaved before this existed: every
environment, the whole Doppler config imported into its Fly app, public.
Nothing adds a descriptor to `api`, `worker`, `scheduler` or `ai_gateway`, and a
test asserts that a product generated without clamd contains no descriptor at
all.

## The file

```yaml
schema_version: 1            # required; the number 1
environments:                # optional; omitted means every configured environment
  - dev
secrets:                     # optional; omitted means policy inherit
  policy: none               # inherit | none | allowlist
  allowlist: [DB_URL]        # only with policy allowlist; exact names
network: private             # optional; public (default) | private
```

It is read strictly. An unknown key, an unknown policy, a wrong type, an empty
list, a duplicate, a lower-case secret name, a pattern in place of a name, a
`DOPPLER_*` name, a misspelt environment and an `allowlist` beside any policy but
`allowlist` are **all errors**, in both readers. A permissive reader turns a typo
into a service deployed where it must not be.

## Readers, one file

| Reader | Where | Uses |
|---|---|---|
| Deploy workflow | `local/scripts/service-descriptor.sh`, called from `.github/workflows/deploy.yml` | which services to deploy to this environment |
| Terraform | `infrastructure/terraform/modules/fly/eligibility`, used by the `fly` module | which Fly apps exist, and which have a public hostname |
| Secrets and verification | `service-secrets.sh`, `verify-private-service.sh` | the secret policy, and the checks on a private service |
| Deploy-time registration | `local/scripts/register-with-control-plane.sh` calls the same script | which services the registry is told are deployed in this environment |
| Registration at provision | `generators/create-koras-app/src/registration/contract.ts` | the same, in the payload sent after `terraform apply` |

The last two matter because the Control Plane **prunes** its service rows by the
list it is sent. Each carried its own copy of "every service, every environment",
and either would have registered clamd in `test`, `stg` and `prod`, where it is
never deployed. The shell one now calls the discovery script rather than keeping
a copy of its pipeline.

`yq` (mikefarah, v4) is needed only to read a descriptor that **exists**. A
product with none never reaches it, so its deploy does not depend on `yq` being
installed, exactly as before. A wrong `yq` fails with a message saying so.

The workflow names no service. It calls the scripts for every service, and each
script reads the descriptor and does nothing where the descriptor says nothing.
There is no clamd conditional anywhere in `deploy.yml`, and a test asserts that.

### Why Terraform and the workflow cannot disagree

They are two implementations of one rule, in two languages, and the cheap way
for two implementations to drift is for one to be edited. So the claim is held
by a test that **runs both** rather than one that compares their text:
`generators/create-koras-app/tests/service-descriptor-parity.test.ts` lays 45
descriptors — valid and not — into a directory, runs the workflow's discovery
script for every environment, applies the real `fly/eligibility` module with
`terraform apply`, and requires identical answers, and requires both to refuse
every invalid one. The module declares no provider, so this needs no credentials
and no network.

In CI the test **fails** if `terraform`, `jq` or the mikefarah `yq` is missing,
rather than skipping, because a skipped parity test is a green check that proves
nothing. `ci.yml` installs Terraform for that reason.

The same descriptor also decides how the README names a product's Fly apps
(`generation/service-descriptor.ts`); that reader only reads the environment list,
and throws on anything it does not understand.

## Environments

A service runs only in the environments it lists. The list may name only `dev`,
`test`, `stg` and `prod` — the mapping is immutable.

For Terraform that is a matrix: a `fly_app` exists for exactly the eligible
service-environment pairs. For the workflow it is the `discover` job's output.
A `terraform plan` of a product with no descriptors was compared against the
plan of the module as it was at `3c53abf`: 112 lines, identical.

## Secret policy

| Policy | `apply` (before the deploy) | `verify` (after it) |
|---|---|---|
| `inherit` | Imports the environment's whole Doppler config, as always — the same two commands, which a test asserts verbatim | Nothing to check |
| `none` | Imports nothing. Never reads Doppler. **Fails if the app already holds any secret.** | Fails if the app holds any secret |
| `allowlist` | Reads Doppler, requires every named secret to exist and be non-empty, imports exactly those. Fails if the app already holds anything else. | Fails if the app holds anything outside the list |

Names are matched exactly, by key. No pattern is ever applied to a name:
allowlisting `DB` does not pull in `DB_URL`, and a `*` or `.*` is rejected when
the descriptor is read.

**Nothing here removes a secret.** A `none` service that already holds secrets
fails, naming them, and says so: `Nothing was removed`. An operator unsets each
by name. This was the decision the stop conditions asked to be made carefully:
deleting from a shared pipeline is irreversible — Fly never returns a value, so
an unset secret cannot be recovered from the app — and a deploy that quietly
clears things is one nobody can reason about. Failing loudly is safe to repeat;
a second run says the same thing again.

No value is printed, ever. Every case in the test runs with sentinel secret
values and asserts they appear in no stdout, no stderr and no recorded call.

Two limits are deliberate and stated: an allowlisted value that contains a line
break, or begins with a quote, is refused, because dotenv has no safe encoding
for it and a silently altered credential is worse than a refused deploy.

## Private services

`network: private` makes the deploy verify, for that service, after it starts:
no public address (only Fly's own private 6PN address is permitted; any other
type, including one the script does not recognise, fails), at least one machine,
every machine started, every machine reporting a health check, all passing.

Terraform withholds a private service from `app_hostnames`. The module also has
no `fly_ip` resource, and a test asserts none is ever added: an app gets a public
address only when `flyctl deploy` allocates one for an `[http_service]` or
`[[services]]` block, so a private service stays private by having neither.

Fly's private network is organisation-wide. It is a private network and not an
isolation boundary between environments, and nothing here claims otherwise.

## Changing the rules

Change `service-descriptor.sh` and `fly/eligibility/main.tf` in the same
commit and add the case to the parity corpus. The test fails otherwise.
