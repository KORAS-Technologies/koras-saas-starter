# supabase/seed

Development fixtures, applied by `make seed` in filename order after the
migrations. Local only -- nothing here is ever applied to a deployed environment.

Empty by default. `make seed` reports that there is nothing to apply rather than
silently succeeding on an empty directory.

Seeds must be re-runnable: use `on conflict do nothing` or `where not exists`
rather than bare inserts, so running `make seed` twice is not an error.
