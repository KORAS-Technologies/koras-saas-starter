#!/usr/bin/env bash
# Qualifies an environment's OWN object store against the upload attack matrix (ADR 0013
# sections 6 and 9; tooling/promotion/provider_qualification.py).
#
#     E2E_DATABASE_URL=postgresql+asyncpg://<app role>:...@127.0.0.1:55434/postgres \
#       bash local/scripts/qualify-storage-provider.sh dev
#
# Starts nothing. The suites use a database only for the file row they seed, never for the
# provider, so E2E_DATABASE_URL must name a DISPOSABLE LOCAL Postgres that already has the schema
# (local/scripts/migrate.sh) and the restricted application role. This script refuses anything
# that is not a loopback host (and so does the Python module, which parses the URL and does not
# trust this glob).
#
# The storage credentials are read, read-only, from the environment's own secret-store config
# (local/config/promotion.yaml names the store) and are never printed. Only disposable objects
# under random tenant prefixes are written, and the suites delete them. They ARE written to the
# TARGET bucket with the target's real credentials: for prod that is a real write to the
# production bucket.
#
# To run the same matrix against a DISPOSABLE LOCAL store you control (an S3-compatible server
# on loopback), export STORAGE_ENDPOINT, STORAGE_BUCKET, STORAGE_ACCESS_KEY and
# STORAGE_SECRET_KEY and set QUALIFY_CREDENTIALS=process. The record then names that store's
# fingerprint, so it never verifies for an environment whose configured store is a different one.
#
# The record goes to the path promotion.yaml names (local/.qualification/<env>.json, git-ignored).
# Exit 0 only on PASS.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_NAME="${1:-}"

case "$ENV_NAME" in
  dev | test | stg | prod) ;;
  *)
    echo "usage: E2E_DATABASE_URL=<disposable local db> $0 <dev|test|stg|prod>" >&2
    exit 2
    ;;
esac

if [ -z "${E2E_DATABASE_URL:-}" ]; then
  cat >&2 <<'MSG'
E2E_DATABASE_URL is not set.

The provider suites need a DISPOSABLE local Postgres for the one row they seed. Start your own
(e.g. a throwaway container on 127.0.0.1), apply local/scripts/migrate.sh and create the
restricted application role, then export
E2E_DATABASE_URL=postgresql+asyncpg://<app role>:<password>@127.0.0.1:<port>/<database>
This script will not start or reset a database for you.
MSG
  exit 2
fi

case "$E2E_DATABASE_URL" in
  *@127.0.0.1[:/]* | *@localhost[:/]* | *@\[::1\][:/]*) ;;
  *)
    echo "refusing: E2E_DATABASE_URL is not a loopback database (only a disposable local one is allowed)" >&2
    exit 2
    ;;
esac

OUT_DIR="${ROOT}/local/.qualification"
mkdir -p "$OUT_DIR"
RECORD="${OUT_DIR}/${ENV_NAME}.json"
JUNIT="${OUT_DIR}/${ENV_NAME}.junit.xml"
rm -f "$RECORD"

cd "$ROOT"
export PYTHONPATH="${ROOT}/tooling${PYTHONPATH:+:${PYTHONPATH}}"

set +e
uv run python -m promotion.provider_qualification run \
  --env "$ENV_NAME" --junit "$JUNIT" --record "$RECORD" \
  --credentials "${QUALIFY_CREDENTIALS:-secret-store}"
STATUS=$?
set -e

if [ "$STATUS" -eq 0 ]; then
  uv run python -m promotion.provider_qualification verify --env "$ENV_NAME" --record "$RECORD" \
    && echo "PASS: ${ENV_NAME} storage provider qualified; record at local/.qualification/${ENV_NAME}.json" \
    && exit 0
  STATUS=1
fi
echo "FAIL: ${ENV_NAME} storage provider is NOT qualified" >&2
exit "$STATUS"
