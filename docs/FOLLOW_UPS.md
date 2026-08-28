# Follow-ups — deliberately not done

> Scope: work that was identified, understood, and **left undone on purpose**,
> with the reason. One list, so that "we knew about that" is checkable rather
> than remembered.
>
> This is not a roadmap (`IMPLEMENTATION_ROADMAP.md` owns forward scope), not a
> risk register (`RISK_REGISTER.md` owns defects found in operation), and not
> the sync backlog (`SYNC_BACKLOG.md` owns the same-thing-true-in-one-place-only
> class). Where an item already has an entry in one of those, this points at it
> rather than restating it — a second description of one problem is how two of
> them come to disagree.

**Opened 2026-08-28**, from the session that applied the Control Plane's staged
promotion and added deploy-time registration.

---

## Blocked here — another repository or a person has to act

### F1 — the eight credentials from control-plane R-65 are still live

- [ ] Rotate four Supabase database passwords (dev, test, stg, prod)
- [ ] Rotate four ZITADEL OIDC client secrets
- [ ] Decide what to do about `output/sample-product`'s published history

**Severity: highest thing on this page.** Everything else here is tidiness by
comparison.

The generator committed a Terraform plan file holding a full state snapshot, and
pushed it. The factory-side defect is closed at four layers and the record is
now `SYNC_BACKLOG.md` C4 — but deleting a file does not unpublish it, and
nothing in this repository can rotate a credential.

`output/sample-product` was checked rather than assumed: the file is untracked
today and `.gitignore` names it, but commit `af81b9b` is reachable from
`develop` and the repository has a GitHub remote. The blob is still there.
Untracking a file does not remove it from history.

**Why not done here:** rotation touches Supabase and ZITADEL, and rewriting
published history is a decision with consequences for every clone. Neither is a
change to this repository.

### F2 — delete the promotion queue entries now that they are applied

- [ ] Remove `starter-promotion.patch`, its `README.md`, and `SYNC_BACKLOG_ENTRIES.md`
      from `koras-control-plane/docs/starter-promotion/`

All three are applied here: the patch as `SYNC_BACKLOG.md` A6, the three written
entries as A4, A5 and E3.

That repository's `OWNERSHIP.md` is explicit that the folder is *"a queue, not an
archive"* and that an applied entry moves upstream and is deleted — *"a promotion
folder that only ever grows is a record of things nobody did."*

**Why not done here:** `koras-control-plane` is read-only from this session.

### F3 — which credential should authorise a product's own re-registration

- [ ] Decide whether a product may hold a token that can rewrite its own registry entry
- [ ] If not, define the narrower machine role the contract already calls for

Deploy-time registration sends `KORAS_CONTROL_PLANE_TOKEN` from that
environment's Doppler config — the same factory-issued bearer token the
generator uses. It works, and it is the smallest number of moving parts.

It is also a trust decision nobody has made. `PRODUCT_REGISTRATION_CONTRACT.md`
§2 says registration should require a role narrower than the human admin one,
and that the narrower role does not exist yet.

**Why not done here:** authorization for the platform API is the Control Plane's
to decide, not the factory's. Recorded in `REGISTRATION_LIFECYCLE.md` under what
is not covered.

---

## Decisions this repository can make, and has not

### F4 — what `packages/control-plane-client` is for

- [ ] Decide whether the package should exist
- [ ] If it should: rewrite its types against the contract
- [ ] If it should not: remove it and the `control_plane_client` capability

Tracked as `SYNC_BACKLOG.md` A4. Its `ProductRegistration` type cannot produce a
request the Control Plane accepts — every field is either missing from the schema
or rejected by `extra="forbid"` — and nothing imports it, which is why no one has
noticed.

**Why not done here:** rewriting the types is an hour. Doing that without
deciding the first question leaves a *third* correct implementation of the same
contract that nothing calls, next to the two that everything calls. The right
order is the other way round.

### F5 — `apps/marketing` declares Tailwind and imports no stylesheet

- [ ] Give it a `globals.css`, or drop `tailwindcss` from its `package.json`

Noted in the promotion patch's own "not included" section and carried into
`SYNC_BACKLOG.md` A6. A PostCSS config there would compile nothing, because
there is no stylesheet for it to compile.

**Why not done here:** it is a design decision about what that application is,
not a defect with one correct fix.

### F6 — the two references deploy-time registration cannot carry

- [ ] Decide whether a newly added application should reach the registry before
      the next `--provision`

`supabase_project_ref` is only reachable through `DATABASE_URL`, which is a
credential and is not read. `vercel_projects` holds per-application repository
secrets that would have to be aggregated into one job to be sent.

Both are upserted and never pruned by the Control Plane, so omitting them ages
them rather than losing them. The single real gap is a **newly added
application**, and it is visible rather than silent — the registry goes on
listing the applications it already knew.

**Why not done here:** closing it means either reading a credential or copying
per-application secrets into a place they are not today, both for a reference
that already survives. Stated in `REGISTRATION_LIFECYCLE.md` rather than fixed
quietly.

---

## Verification that has not happened

### F7 — nothing has exercised the register job in a real pipeline

- [ ] Observe the `register` job run in a generated project's deployment
- [ ] Confirm the Control Plane's stored references change as a result

What has been checked: the payload validates against the Control Plane's real
request model; the script refuses on a generated control-plane project with a
URL and token configured; every failure and skip path is asserted by
`registration-lifecycle.test.ts`.

What has not: a run against a live Control Plane, with a real Doppler config and
a real deployment.

**Why not done here:** deploying and provisioning are out of scope for this
session by instruction.

### F8 — the `--with` / `--without` generation paths remain untested

- [ ] Generate with optional components and read the output

Pre-existing, tracked as R-037 and `SYNC_BACKLOG.md` D5, and named in `CLAUDE.md`
as the next step. Recorded here only because it now also covers the register job:
that job comes from the shared template and is present regardless of component
selection, but nothing has generated a product with optional components and
checked it.

**Why not done here:** it is the repository's existing next step and larger than
this session's scope.
