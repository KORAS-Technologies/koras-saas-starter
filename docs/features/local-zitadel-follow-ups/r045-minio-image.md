# R-045, replacing the unpullable MinIO image

**Problem.** `profiles/product/template/local/docker-compose.yml.hbs` runs
`storage` on `minio/minio:latest`, which is no longer published. `make dev`
fails on any machine without that tag cached. CI hides this behind a
`sleep infinity` stand-in, in the `local-zitadel-secure` job of
`generator-integration.yml`.

## Options, for the owner to choose
| Option | For | Against |
|--------|-----|---------|
| A. Build MinIO from source locally, the way `.github/actions/start-minio` does in CI | One S3 server across CI and local, and the secure-files suites already trust it | Every developer's first `make dev` runs a Go build. The source pin needs maintaining. |
| B. A published, pinned community MinIO image, by digest | Fast; no build | Third-party provenance. Needs a supply-chain review and digest pinning. |
| C. Another S3-compatible server (for example SeaweedFS or Garage) | Actively published images | Behaviour differs on exactly what the secure-files suites test (`x-amz-copy-source`, checksums). Every storage suite must re-run against it. |

**Recommendation:** A or B, decided on provenance. C only if the
secure-files suites pass against it unchanged.

## Steps
1. Owner picks the option and the pin (a digest, not `latest`).
2. Change the template's `storage` image. Keep the health check meaningful
   (`mc ready local` or an equivalent HTTP probe), and bind the ports to
   loopback (see `loopback-local-services.md`).
3. In `local-zitadel-secure`, delete the stand-in step and require `storage`
   healthy after `stack.mjs up`. The job then proves the real stack starts.
4. A generator test pins the image to a digest, so `latest` cannot return.
5. Record in R-045 what was verified and on which run.

**Exit.** A fresh runner with no cached images completes `stack.mjs up` with
every service healthy. The secure-files suites pass against the chosen image.
