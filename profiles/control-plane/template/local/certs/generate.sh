#!/usr/bin/env bash
# Generates locally-trusted TLS certificates using mkcert.
# Run once after `mkcert -install`.
set -euo pipefail

CERT_DIR="$(cd "$(dirname "$0")/.." && pwd)/certs"
mkdir -p "$CERT_DIR"

if ! command -v mkcert &>/dev/null; then
  echo "Error: mkcert is not installed."
  echo "  macOS:   brew install mkcert"
  echo "  Linux:   https://github.com/FiloSottile/mkcert#installation"
  echo "  Windows: choco install mkcert"
  exit 1
fi

mkcert -install

domains=(
  "app.localhost"
  "admin.localhost"
  "www.localhost"
  "portal.localhost"
  "api.localhost"
  "auth.localhost"
)

for domain in "${domains[@]}"; do
  mkcert \
    -cert-file "${CERT_DIR}/${domain}.pem" \
    -key-file  "${CERT_DIR}/${domain}-key.pem" \
    "${domain}"
  echo "Generated: ${domain}"
done

echo ""
echo "Certificates written to: ${CERT_DIR}"
echo "Mount this directory read-only into the Caddy container."
