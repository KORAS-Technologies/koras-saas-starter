# Settings framework — sync matrix

What each of the three repositories owes this feature, and what it got.
Written 2026-09-19, after the work.

How the three repositories relate — which is canonical, which receives a
hand-carried commit, and why the Control Plane receives nothing but one file —
is in `docs/features/PROFILE_SYNC_MATRIX.md` and is not restated here. Read that
first if this is the first sync matrix you have opened.

## The short version

| Repository | What it holds | How it got it |
|------------|---------------|---------------|
| `koras-saas-starter` | Everything, as template | Written here |
| `output/koras-e2e-shop` | A generated product's share | One `chore: sync` commit |
| `koras-control-plane` | A parallel implementation | Written there, against the contract |

## The starter

Canonical. Both template layers carry part of it, and which layer decides more
than it looks.

| Piece | Layer | Why that layer |
|-------|-------|----------------|
| `python-packages/koras-settings` | `_shared` | Both profiles resolve settings. The Control Plane's own resolution uses the same package, so a scope refusal cannot differ between them |
| The three migrations | `product` | A Control Plane has no tenants to snapshot settings for |
| The catalogue, store and routers | `product` | Same |
| The two pages, the provider, the form | `product` | Same |
| The data table | `product` | The console has its own table, in its own repository, and always has |

No file exists in both profile templates, which
`shared-template-parity.test.ts` asserts structurally rather than by listing
paths.

### Not gated by a capability

There is no `settings` entry in `profiles/product/manifest.yaml`. A product
generated with `--without` anything still has the whole framework, because
`seed_tenant` runs inside tenant creation and every product creates tenants. The
rule is the one the governance work wrote down: a table is gated only when no
foundation code and no foundation migration reaches it.

## The shop

One `chore: sync the settings framework from the starter` commit, carried by the
three-way method — the starter before the work, the starter after, and the shop
— so a file the shop had written for itself could not be silently reverted.

It carried 37 new files, 21 changed and 1 deleted. Exactly one file needed a
hand: `packages/branding/src/index.ts`, which the shop had edited for itself and
which the template also changed, so it was merged rather than taken. The
manifest digest is regenerated rather than merged; it is meant to change.

The `chore: sync` prefix is not decoration. The shop's own
`tests/unit/test_migration_numbering.py` reads it to tell a carried migration
from one the shop wrote, and a sync committed under any other prefix fails that
test.

### And one commit that is the shop's own

`/dashboard/orders`, `GET /shop/orders` and 300 seeded orders are **not** a
sync. The starter has no orders domain and nothing in that commit will ever be
carried back. It exists because the framework arrived in a repository with
nowhere to watch it work: `grid.pageSize` defaults to fifty and the largest list
this estate could draw was forty rows, so the setting resolved correctly and
changed nothing anybody could see.

Two commits rather than one, and deliberately so. One commit would have put
shop-authored files under a prefix that means "this came from the starter",
which is the thing the sync method exists to prevent.

## The Control Plane

Not code-synced. Its share is a parallel implementation against an extended
contract, and the only byte-identical file is
`contracts/product-platform.v1.json`.

| What | Where |
|------|-------|
| The contract | `contracts/product-platform.v1.json`, byte-identical both sides |
| The reference product | `tests/contract/reference_product.py` |
| Its own tables | `supabase/migrations/00045_product_settings.sql` |
| Repository, schemas, router | `services/api/koras_api/*/settings.py` |
| The sync and push tasks | `services/worker/koras_worker/product_settings.py` |
| The console | `apps/admin/src/app/settings/` |
| Paging in its own table | `apps/admin/src/components/ui/DataTable.tsx` |

It reads a product's published catalogue and writes platform defaults back. The
write route is the part that needed ADR 0007: the contract's `no_direct_writes`
rule and the decision that *the platform may only act in the direction that
keeps data* both had to be squared with a platform that sets a default. A
default is not a customer's data, and setting one cannot remove a value an
organisation holds.

Its console table pages with links rather than client state, because the
console's tables are server-rendered and always have been. It does **not** read
`grid.pageSize`: those settings belong to a customer, and platform staff are not
a customer of the product they are administering.

## What each repository does not have

| Repository | Deliberately absent |
|------------|---------------------|
| Starter | Any page using the shared table. There is no list long enough in a freshly generated product, which is why the validating page is in the shop |
| Shop | Nothing of the framework. It is level with the starter as of the sync commit |
| Control Plane | The three product tables, the snapshot, the two customer pages, the shared resolver's HTTP surface |

## Repositories deliberately untouched

`Docoris`, `Dianova`, `LegalApp` and every other real product. The brief says
so, and nothing in this feature was applied to any of them.
