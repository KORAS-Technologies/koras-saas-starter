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

**Closed 2026-10-10**, all three steps.

1. **The construct.** A hashbang line that ends in CRLF, and nothing else in
   the file: `#!/usr/bin/env node\r\nexport const a = 1\r\n` reproduces it in
   two lines. Vite 7.3.6's SSR transform finds the hashbang with `/^#!.*\n/`,
   and `.` does not match `\r`, so on a CRLF file it finds none, hoists the
   module's imports to offset 0 -- above the hashbang -- and the hashbang is no
   longer the first thing in the module. `stack.mjs` is the only one of the six
   modules that has both a hashbang and imports, which is why the other five
   loaded. Found by bisecting a generated copy; the same file with only its
   first line converted to LF loads.
2. **Both, not one.** `.gitattributes` is `* text=auto eol=lf` now, in the
   starter and in the generated project's template: every text file is LF in a
   checkout on every platform, and `*.bat`, `*.cmd` and `*.ps1` stay CRLF
   because their rules come later. A list of extensions was the thing that
   failed -- it had `*.sh` and missed `*.sh.hbs`, `*.mjs` and every YAML file
   -- so a longer list would only have moved the gap. The object store was
   already LF for every one of the 1,673 text files that checked out CRLF, so
   this changed no content and needed no renormalisation. And the writer
   normalises any generated file that **starts with a hashbang**, whatever it
   is called, beside the names it already normalised, so a checkout that does
   not honour `.gitattributes` still produces a `stack.mjs` that loads.
   The twelve `\n`-anchored failures were in `local-zitadel-secure.test.ts`
   itself (T-U2, T-U4, T-U6, once per generated project), over a CRLF
   `docker-compose.yml` rendered from a CRLF template; the attributes rule is
   what closes those.
3. **The Windows job** sets `core.autocrlf=true` before checkout, fails if any
   text file other than the Windows-native scripts is checked out CRLF, runs
   the whole of `local-zitadel-secure.test.ts` and the line-ending tests from
   `generation.test.ts`, then generates a product and runs its `stack.mjs
   status` under plain `node`.

One claim made about this on 2026-10-10 did not hold: generated shell scripts
and Dockerfiles were **not** CRLF on a Windows-generated product. The writer
already normalised `*.sh`, `*.bash`, `*.mk`, `Makefile`, `Dockerfile` and
`*.Dockerfile` by output name, and `.sh.hbs` and `Dockerfile.hbs` render to
those names. What it missed was a script named anything else.

A working tree checked out before this change keeps its CRLF files until git
rewrites them; `git rm --cached -r -q . && git reset --hard` on a clean tree,
or a fresh clone, brings it level. Nothing shows as modified in the meantime,
because the index was LF all along.

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
