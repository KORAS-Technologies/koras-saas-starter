# Settings — Developer Guide

How to add a setting, how to read one, and the four things that will bite.

What the framework *is* is `docs/SETTINGS_ARCHITECTURE.md`. This is the
day-to-day.

## Adding a setting

One file. `services/api/koras_api/settings_catalogue/product.py` in the
generated product ships an empty list, and that is where a product's own
settings go:

```python
from koras_settings import Category, DataType, Scope, SettingDefinition

SETTINGS: list[SettingDefinition] = [
    SettingDefinition(
        key="shop.lowStockThreshold",
        category=Category.GENERAL,
        data_type=DataType.INTEGER,
        default=5,
        scope=Scope.GLOBAL_ORG,
        minimum=0,
        maximum=10_000,
        label_key="settings.def.shop.lowStockThreshold.label",
        description_key="settings.def.shop.lowStockThreshold.description",
    ),
]
```

Then add the two i18n strings, in every language the product offers, and you are
done. No page is edited, no migration is written, no API route is added, and the
Control Plane picks it up from the published catalogue.

The key is `group.name`, camelCase after the dot. `__post_init__` refuses
anything else at import, so a wrong key is a process that does not start rather
than a setting that half works.

### Choosing the scope

| If | Scope |
|----|-------|
| Only KORAS decides it | `GLOBAL_ONLY` |
| An organisation decides it for everyone in it | `GLOBAL_ORG` |
| A person decides it for themselves | `GLOBAL_ORG_USER` |

`user_visible` is only meaningful on `GLOBAL_ORG_USER`, and setting it anywhere
else is refused at import. That is deliberate: a setting that appears on My
preferences and is then refused by the API is a bug the catalogue can prevent
rather than one the page has to handle.

### Do not put a secret in one

The database refuses a key matching `secret`, `token`, `password`, `passwd`,
`credential`, or any spelling of an api, access, private or secret key. Doppler
is the secret authority. If a feature needs a credential, it needs Doppler and a
provider seam, not a setting.

## Reading a setting

### In a React component

```tsx
const pageSize = useSetting<number>('grid.pageSize')
```

The provider is resolved once in the dashboard layout, so this costs nothing and
makes no request. **Do not fetch settings in a component.** One request per
session is the design; a component that fetches turns it into one per component.

### In a server component

The layout already has them. `effectiveSettings()` in `apps/web/src/lib` is
memoised per render pass, so calling it in a page does not make a second
request.

### In Python

```python
resolution = resolve_all(definitions, global_values, tenant_values, member_values)
```

`resolve_all` returns a `Resolution` carrying a `Resolved` per key — value,
source, whether the caller may override it, and the two rungs below. Everything
that resolves a setting anywhere goes through this function; there is no second
implementation, in this repository or in the Control Plane.

## Using the shared table

```tsx
<KorasDataTable data={orders} columns={columns} labels={labels} caption="Orders" empty="No orders yet." />
```

Page size, paging, the offered sizes, the sticky header and the row density
come from the customer's `grid.*` settings.

To override one, pass it:

```tsx
<KorasDataTable data={orders} columns={columns} labels={labels} … pageSize={10} />
```

An explicit prop always wins. That precedence lives in `chooseValue` in
`packages/ui/src/data-table/paging.ts`, in one place, so it cannot be applied
inconsistently by a call site that reimplements it.

**Do not create a second data table.** The brief's non-goals say so and the
reason is this framework: a page-local table is a page that does not honour any
of these settings, and nobody finds out until a customer changes one.

**`columns` and `rowKey` must be built in a Client Component.** `KorasDataTable`
is `'use client'`, and `DataTableColumn.cell` and `rowKey` are functions.
Building them in the Server Component page and passing them straight in —
exactly the shape shown above, with no wrapper — throws at request time:
"Functions cannot be passed directly to Client Components." TEST-SET-01 found
this the hard way, live, in the one page that ever tried it. Fetch `data` in
the page, build `labels` with `dataTableLabels(t)` (strings, safe to cross), and
put the actual `<KorasDataTable>` call — with `columns` and `rowKey` built
inside it — in a small colocated `'use client'` component that takes `data` and
`labels` as props:

```tsx
// orders-table.tsx
'use client'
export function OrdersTable({ data, labels }: { data: Order[]; labels: DataTableLabels }) {
  const columns: DataTableColumn<Order>[] = [
    { key: 'customer', header: 'Customer', cell: (o) => o.customer },
  ]
  return (
    <KorasDataTable
      data={data}
      columns={columns}
      labels={labels}
      rowKey={(o) => o.id}
      caption="Orders"
      empty="No orders yet."
    />
  )
}

// page.tsx — the Server Component
export default async function OrdersPage() {
  const [orders, t] = await Promise.all([fetchOrders(), translator()])
  return <OrdersTable data={orders} labels={dataTableLabels(t)} />
}
```

`labels` is safe to build on the server because `DataTableLabels` is all
strings — `showing` and `page` are `{placeholder}` templates the table fills in
once it knows the numbers, the same pattern `SettingsFormLabels.resetTo` uses.
`data` is safe because it is plain JSON. `columns` and `rowKey` are not, because
they hold functions, and no amount of memoising or hoisting them to module
scope changes that — the restriction is about crossing the boundary as a value,
not about where the function was defined.

## The five things that will bite

### 1. A setting whose absence means "work it out"

If the sensible behaviour when a setting is unset is *infer it from context*,
that inference dies the moment the setting is snapshotted, because a new
organisation is given a value.

Express the inference as a value. `general.language` offers `auto` for exactly
this reason, and the rule is in ADR 0007:

> a setting whose absence means "infer it from context" must express that
> inference as one of its values, or the snapshot will silently end the
> inference.

### 2. A setting nothing honours

Five `grid.*` settings ship with `surfaced=False` because the shared table does
not implement them yet. If you add a setting the product does not read, mark it
the same way. A control a person can change that changes nothing is worse than
one that is not offered, because it costs them the time to find out.

### 3. Changing a default does not change anybody

Editing the `default` on a definition affects organisations created *after* the
deploy. Existing ones hold a snapshot. That is the requirement, not a bug — and
it means "we changed the default and nothing happened" is the expected outcome
rather than something to debug.

To move existing organisations, somebody has to decide to, and it is a
deliberate act with an audit trail rather than a side effect of a deploy.

### 4. An organisation reset is a copy, a person reset is a delete

They read the same on the page and are different in the database.
`tenant_setting_values` keeps the row and writes the platform's current value
into it; `member_setting_values` deletes the row. A tenant that stopped holding
a row would start following the platform again, which is the snapshot rule
broken by a button.

### 5. A label that needs a value is a string, never a function

Every label type this package defines — `SettingsFormLabels`, `ReportingLabels`,
`DataTableLabels` — is passed from a Server Component to a Client Component.
A field built as `(value) => t('key', { value })` type-checks and throws at
request time, because a function cannot cross that boundary. Build it as a
`{placeholder}` template instead and fill it on the client, with `withValue` or
the local `fill` — see `DataTableLabels` and "Using the shared table" above.

## Tests you are expected to add

| You added | Add a test in |
|-----------|---------------|
| A setting | Nothing. The catalogue tests walk every definition |
| A new data type or control | `python-packages/koras-settings/tests/` |
| A page or a field renderer | `generators/create-koras-app/tests/product-settings.test.ts` |
| A table or a policy | `supabase/tests/`, numbered, and the RLS coverage list |

The catalogue suite walks every registered definition, so a new setting is
already covered for key shape, scope consistency, bounds, options and the
presence of both i18n keys in all three languages. That is the point of a
code-declared catalogue: the tests are written once against the registry rather
than once per setting.

## Where the pieces are

Paths below are relative to a generated product.

| Piece | Path |
|-------|------|
| Definitions, registry, coercion, resolver | `python-packages/koras-settings/` |
| The standard catalogue | `services/api/koras_api/settings_catalogue/standard.py` |
| A product's own settings | `services/api/koras_api/settings_catalogue/product.py` |
| Reads and writes | `services/api/koras_api/core/settings_store.py` |
| The routes | `services/api/koras_api/routers/settings.py` |
| The platform's routes | `services/api/koras_api/routers/platform.py` |
| The provider and form | `packages/ui/src/settings/` |
| The table | `packages/ui/src/data-table/` |
| The two pages | `apps/web/src/app/dashboard/settings/` and `.../preferences/` |
| The tables | `supabase/migrations/00029_settings.sql` and after |
