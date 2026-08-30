# Registration Lifecycle

> Scope: this repository — the factory, its generator, and the templates both
> profiles ship. The **contract** is not owned here. It lives in
> `koras-control-plane/docs/PRODUCT_REGISTRATION_CONTRACT.md` and is
> authoritative for what a registration request contains, how it is
> authenticated, and what a product must serve in the other direction. Where
> this document and that one disagree, that one is right.

## The question this answers

A product registers itself with the Control Plane. *When?* Until 2026-08-28 the
answer was "once, at generation, and never again", and that answer was nowhere
written down — it was a property of the code that nothing stated and nothing
tested.

That mattered because the Control Plane's reconciliation compares the registry
against reality. A registry that silently ages does not read as stale; it reads
as drift. Every reference that moved after generation day — a service added, an
environment provisioned later, a rotated ZITADEL project — became a difference
between the registry and the estate with no explanation attached, and the
explanation was always the same one: nobody had told the registry.

## The decision

**Both.** Generation-time registration stays exactly as it is, and each
environment re-registers itself at the end of its own deployment.

| | Generation-time | Deploy-time |
|---|---|---|
| Where | `generators/create-koras-app/src/registration/` | `local/scripts/register-with-control-plane.sh`, called from `deploy.yml` |
| Runs | once, after the first `terraform apply` | after every successful deployment of an environment |
| Sends | all four environments in one request | the one environment that just deployed |
| Source of truth | Terraform outputs | the repository, plus non-secret settings in Doppler |
| Credentials | `KORAS_CONTROL_PLANE_URL` / `_TOKEN` from Doppler | the same two names, from that environment's Doppler config |

The alternative — declaring the registry generation-time-only and having
reconciliation treat missing references as expected — was considered and
rejected. It is a legitimate position, and it is cheaper. It was rejected
because it makes reconciliation weaker in exactly the case reconciliation exists
for: a reference that is *absent* and a reference that is *wrong* would become
indistinguishable, and the Control Plane would have to stop reporting the second
in order to stop reporting the first.

## Why the two passes carry different things

They are not two implementations of one payload. They see different things, and
each sees something the other cannot.

**Generation-time sees the whole estate at once**, because `terraform apply` has
just returned every output for every environment. That is the only moment
`supabase_project_ref` and the Vercel project ids are available as plain values.

**Deploy-time sees what is actually deployed**, which generation-time can only
predict. It reads the service list from the repository by the same rule the
`discover` job uses, so a service added six months later is registered the first
time it deploys.

What deploy-time cannot carry, and why:

| Field | Why not | Consequence |
|---|---|---|
| `supabase_project_ref` | only reachable through `DATABASE_URL`, which is a credential and is not read | the generation-time value stands |
| `vercel_projects` | the project ids are per-application repository secrets; aggregating them into one job means copying them somewhere they are not today | the generation-time value stands; a **newly added application** is not registered |

Both fields are upserted and never pruned by the Control Plane, so omitting them
ages them rather than losing them. The newly-added-application case is the one
real gap, and it is visible rather than silent: the registry keeps listing the
applications it already knew.

What deploy-time carries that generation-time cannot:

- **`zitadel_client_id`.** The Terraform output is marked sensitive, so the
  generator will not read it — correctly. Un-marking an output so a payload can
  carry it is precisely the trade the contract exists to refuse. In Doppler it
  is an ordinary non-secret setting, and the Control Plane's schema lists it
  among the identifiers that are public by nature.
- **A `platform_api_base_url` that has been proved.** The `verify` job has just
  confirmed that host is serving and reporting this environment. At generation
  time it is a name Terraform created, not a service that answered.

## What makes a single-environment request safe

Read out of the Control Plane's persistence layer —
`koras-control-plane/services/api/koras_api/repositories/products.py` —
rather than assumed:

| Object | Semantics | Consequence for a partial request |
|---|---|---|
| `product_environments` | upsert, no prune | sending only `prod` leaves dev, test and stg untouched |
| `infrastructure_references` | upsert, no prune | an omitted reference goes stale; it does not disappear |
| `product_services` | upsert **and prune** within the environment | the service list must be right, or rows are deleted |
| `products` | every column overwritten from the request | an omitted column is written as NULL |

That last row is the sharp edge, and it is why the script refuses rather than
guesses. `primary_domain`, `starter_version` and `profile_version` are read from
`terraform.tfvars` and `.koras/project.yaml`; if any cannot be read, nothing is
sent. A registration that quietly empties three columns is worse than one that
did not run.

It also closed a defect on the generation-time side. `buildRegistration` had
declared `starter_version` and `profile_version` on its payload type since the
type was written and populated neither, so every product registered so far reads
as generated from nothing in particular — and those are the two fields the
contract provides specifically so the Control Plane can identify products
needing an upgrade. They are populated now.

## Why the Control Plane never runs this

`profiles/control-plane/manifest.yaml` sets `registers_as_product: false`. The
Control Plane is platform infrastructure, not an entry in its own product
registry; registering it would make the platform a customer of itself.

The trap is that `deploy.yml` is **shared**. It lives in
`profiles/_shared/template/.github/workflows/`, neither profile ships its own,
and a re-registration job added there runs in the Control Plane's pipeline as
readily as in a product's.

The obvious guard — a Handlebars conditional on `registersAsProduct`, which the
generator does expose to the template context — is not available, and the reason
is worth stating because it is not obvious. `deploy.yml` is not a `.hbs` file
and must not become one: it is dense with GitHub `${{ … }}` expressions, and
Handlebars parses `{{ secrets.FLY_API_TOKEN }}` as a mustache and renders it
empty. The result would be a workflow that looks correct and authenticates as
nobody. There is a test asserting exactly this, and it predates this work.

So the guard is at runtime, following the precedent already set by
`check-rls-connection.sh` in the same workflow: the script reads
`.koras/project.yaml` — the authoritative record of what a repository is — and
exits cleanly on `control-plane`, having sent nothing. An unrecognised profile
is an error rather than a silent pass.

That is the fourth of four independent refusals:

1. the generator's `decideRegistration` guard, which reads the manifest
2. this script, which reads `.koras/project.yaml`
3. a validator on `profile` in the Control Plane's request schema
4. a constraint in the Control Plane's database

Four is not excessive for this one. A wrongly registered Control Plane is not a
failed request; it is a platform that believes it is its own tenant.

## Failure behaviour, and why it is asymmetric

The rules match the generator's exactly, deliberately — one rule described once
rather than two that drift.

| Situation | Result |
|---|---|
| `KORAS_CONTROL_PLANE_URL` unset | **skip**, exit 0 |
| URL set, neither `KORAS_CONTROL_PLANE_KEY_JSON` nor `KORAS_CONTROL_PLANE_TOKEN` set | **fail** |
| Key set but malformed, or with no `KORAS_CONTROL_PLANE_PROJECT_ID` | **fail** — never a fallback to the token |
| Key set and the ZITADEL exchange refuses it | **fail** |
| URL not https (and not loopback) | **fail** |
| Control Plane unreachable | **skip**, exit 0 |
| `422` from the Control Plane | **fail**, and say it is a contract mismatch |
| Identity fields unreadable | **fail**, having sent nothing |

An unconfigured Control Plane is the documented bootstrap order (R-001): the
first product in a new estate is provisioned before the registry it would
register with exists. A *misconfiguration* is not, and is reported loudly,
because a misconfiguration reported as nothing-to-do is one nobody fixes.

Unreachable is a skip because the deployment itself already succeeded and the
next deployment re-sends the same request. Failing a green deployment over a
registry that was briefly down would train people to ignore the job.

## Neither pass is a substitute for the other

Generation-time is what makes a product exist in the registry at all, and it is
the only pass that carries every environment and every reference. Deploy-time is
what keeps that entry from ageing.

A product generated before its Control Plane existed has no entry until its
first deployment after one is live — which is the R-001 recovery path, and it is
now automatic rather than a manual `curl` nobody remembered to run. The script
is runnable by hand for the same purpose:

```bash
bash local/scripts/register-with-control-plane.sh prod
```

## What is not covered

- **Deregistration.** Nothing removes a product from the registry when its
  repository is deleted. The Control Plane's teardown owns that question; see
  R-036 and the provisioning runbook.
- **Which credential should authorise a product's own re-registration.** Still
  open, and the reason the deploy-time job is off by default since 2026-08-30.
  The script uses `KORAS_CONTROL_PLANE_TOKEN` from that environment's Doppler
  config — a ZITADEL token for the estate-wide `registrar` service user, which
  nothing issues or provisions, and NEW_PRODUCT_WALKTHROUGH.md §A.2 is the only
  description of it that exists. The contract (§2) says registration should
  require a role narrower than the human admin one, and that the narrower role
  does not exist yet. Whether a *product* should hold a credential that can
  rewrite any product's registry entry is a Control Plane authorization decision
  rather than a factory one.

  The generator's half of this changed and this did not: the generator mints
  from a key per call (F2a), while the script still reads a stored token
  deliberately. Giving a product the *key* would be strictly worse than the
  token — a key does not expire — so the credential form was not "fixed" here
  until the authority question is answered.
- **The generated `packages/control-plane-client`** — deleted 2026-08-30, and
  listed here so nobody goes looking for it. It performed neither pass and its
  types could not produce a request the Control Plane accepts. `SYNC_BACKLOG.md`
  A4 and `FOLLOW_UPS.md` F4.
- **`--with` / `--without` generation paths**, which remain untested (R-037).
  The register job is emitted from the shared template and is therefore present
  regardless of component selection, but nothing has generated a product with
  optional components and read the result.
