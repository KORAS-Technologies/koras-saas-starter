# Koras Postman tooling

Generates a Postman DEV collection and environment from a KORAS API's real,
currently implemented routes. See `docs/api/postman-standard.md` for the
design and the rules; this file is the how-to.

Copied verbatim into every generated project (`shared_assets` in both profile
manifests), so the same scripts run against the Control Plane and any
product.

## Quick start

From a repository root that has `services/api/koras_api/main.py` (every
KORAS Control Plane or product repository):

```bash
pnpm postman:generate
```

or, if the repository's Python dependencies are managed by `uv`:

```bash
pnpm postman:generate -- --python "uv run --no-project python"
```

Writes `postman/<Name>-DEV.postman_collection.json` and
`postman/environments/DEV.postman_environment.json`.

## Scripts

| Script | Does |
|---|---|
| `extract_openapi.py` | Imports the API's own `koras_api.main:app` and calls `app.openapi()`. No server starts, no database or network call happens. |
| `openapi-to-postman.mjs` | OpenAPI 3.x JSON -> a Postman Collection v2.1 (folders by tag, bearer auth, example request bodies from the real schemas, per-request tests from the operation's declared responses). |
| `merge-custom.mjs` | Splices `templates/<profile>-custom.postman_collection.json` (CI Smoke, Security & Negative Tests) into the generated collection. |
| `generate-environment.mjs` | Scans the final collection for every `{{variable}}` it references and writes a DEV environment with blank/placeholder values. |
| `generate.mjs` | Runs the four above in order. This is what `postman:generate` calls. |

Each script also runs standalone — useful for regenerating just the
environment after hand-editing the custom template, for example:

```bash
node tooling/postman/scripts/generate-environment.mjs \
  --collection postman/Docoris-DEV.postman_collection.json \
  --out postman/environments/DEV.postman_environment.json \
  --name "Docoris - DEV" --base-url-var product_base_url --base-url http://localhost:8001
```

## Importing into Postman

Full step-by-step walkthrough (import, environment, access token, running
CI Smoke, troubleshooting): `docs/api/postman-import-setup.md`.

## Adding product-specific security or smoke coverage

Edit `templates/product-custom.postman_collection.json` (or
`control-plane-custom.postman_collection.json`) in the **starter** — not the
copy inside a generated repository, which is overwritten the next time that
repository is hand-synced from the starter (see the starter's own
`docs/CLAUDE_CODE.md` / `SYNC_BACKLOG.md` for how that sync works). Every
custom request should name, in its `description`, the file and function that
implements the behavior it asserts.

## Variables every generated environment carries

`generate-environment.mjs` always includes a base set regardless of whether
the current collection happens to reference it yet —
`control_plane_base_url`, `product_base_url`, `api_version`, `access_token`,
`organization_id`, `tenant_id`, `tenant_slug`, `product_id`, `product_key`,
`user_id` — plus every path parameter the real API declares (so a product
with `account_id`, `import_id`, `job_id` in its routes gets those too,
automatically, because it scans the generated collection rather than a fixed
list).

## Known gaps

See "What this does not (yet) do" in `docs/api/postman-standard.md`: no
committed OpenAPI file, no CI/Newman wiring, and Security & Negative Tests
cover the shared auth/tenant boundary rather than every per-route
authorization rule.
