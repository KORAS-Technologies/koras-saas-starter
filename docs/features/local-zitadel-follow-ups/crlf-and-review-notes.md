# Windows CRLF compatibility and the remaining review notes

## 5a. CRLF
**Found 2026-10-10.** With `core.autocrlf=true`, a working copy of
`stack.mjs.hbs` with CRLF line endings makes `local-zitadel-secure.test.ts`
fail to import the rendered `stack.mjs` ("SyntaxError: Invalid or unexpected
token"). It took down four `describe` blocks. `node --check` accepts the same
file, so the break is in vitest's module loading, not in Node. The Windows CI
job runs only `-t masterkey.mjs`, so it cannot see this.

Steps:
1. Reproduce from a fresh CRLF clone and find the exact construct vitest
   rejects. Do not guess.
2. Choose: add `*.mjs` and `*.mjs.hbs` to `.gitattributes` with `eol=lf`, as
   `preflight.sh` already is, or make the generator normalise line endings on
   write.
3. Widen the Windows job to the whole of `local-zitadel-secure.test.ts` on a
   real CRLF checkout, and also run a generated `stack.mjs status` under plain
   `node`.

## 5b. Remaining notes from the security and QA reviews
| # | Note | Severity | Proposed fix |
|---|------|----------|--------------|
| 1 | On Windows, PAT files in the repo (`machinekey/pat`, `bootstrap/login-client.pat`) and the state file get no ACL, so on `C:\repos` other local users can read an IAM_OWNER token | Low | Apply `writeSecretFile`'s single-principal ACL to token files, then verify it |
| 2 | On Windows, `writeSecretFile` writes the secret before it restricts the ACL | Low | Create the file empty, restrict and verify, then write; unlink on any failure |
| 3 | A failed `rotate-pat` leaves the new token valid and untracked | Low | Best-effort delete of the new token id in the catch, reporting any leftover |
| 4 | T-I14 never shows the old login-client token is refused; T-I6 never reads the login-client token's expiry back | QA Medium | Add both assertions to `run.sh` |
| 5 | `restart: unless-stopped` lets Docker restart legacy-recovery ZITADEL without going through `stack.mjs`'s gate | Low | `restart: "no"` in the legacy override |
| 6 | `doppler-check` checks only the configs it lists | Low | Enumerate every config with `doppler configs --json` |
| 7 | The Windows ACL check matches a username, not a SID | Info | Compare against `whoami /user` |
| 8 | CI's `::add-mask::` with `%` in the password may register a different mask | Info | Percent-encode before masking |
| 9 | T-I12 treats any 10 s without a callback as a refusal | QA Low | Assert ZITADEL's error text on the login page |
| 10 | T-E7 in CI counts session-key packets but never compares the key ID with the pinned subkey | QA Low | Compare the key ID |
| 11 | `provision.py` run by hand does not confirm the running `instanceId` | Info | Compare with `/admin/v1/instances/me` before writing |

Items 1 to 4 belong before Stage 4.3B. The rest can be batched.
