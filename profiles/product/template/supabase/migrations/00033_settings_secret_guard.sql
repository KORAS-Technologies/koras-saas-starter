-- Migration: 00033_settings_secret_guard
-- The secret guard looked one level deep, and said it looked everywhere.
--
-- `00029_settings.sql` shipped `setting_holds_no_secret` with this comment:
--
--     A key called `integrations.apiToken` is a credential whatever it holds,
--     and a value `{"secret": "..."} ` is one whatever the key is called.
--
-- The first half was true. The second was true at depth one and false at depth
-- two, because the check was `jsonb_each`, which yields the top-level members
-- of an object and nothing else. Found on 2026-09-19 by the first independent
-- review this framework had, and confirmed against a real Postgres before this
-- was written:
--
--     setting_holds_no_secret('x.config', '{"auth":{"token":"ghp_x"}}')  → true
--     setting_holds_no_secret('x.config', '[{"secret":"s"}]')           → true
--     setting_holds_no_secret('x.config', '{"a":[{"b":{"apiKey":"s"}}]}')→ true
--
-- `true` means "holds no secret". All three were stored.
--
-- The framework supports `DataType.OBJECT` and a product may declare one, so
-- this was not hypothetical: an administrator storing an integration's
-- configuration with a nested `auth.token` had it accepted, written in
-- plaintext, and then served to every member of the tenant by
-- `GET /settings/effective`, which needs no permission.
--
-- ── What changed ─────────────────────────────────────────────────────────────
--
-- `jsonb_path_exists` with `$.**`, which walks the whole document including
-- through arrays. Three details, each of which cost a run to find:
--
-- `.keyvalue()` refuses to be applied to a scalar, so a setting holding `50`
-- raises rather than answering. `silent => true` suppresses that — and then
-- returns **NULL**, not false, so the whole expression becomes NULL. A CHECK
-- constraint treats NULL as satisfied, so the guard would have passed
-- everything by accident while looking correct. `coalesce(..., false)` is what
-- makes the suppression mean "found nothing".
--
-- ── The word list ────────────────────────────────────────────────────────────
--
-- `signing`, `encryption` and `ssh` join the nouns, and `signingKey`,
-- `encryptionKey` and `sshKey` join the `_?key` group. The review found
-- `integrations.webhookSigningKey` accepted at every level: it contains none of
-- the original words, and `key` on its own is deliberately not one of them
-- because `shop.sortKey` is a column name and a guard that refuses the honest
-- case is a guard somebody turns off. That reasoning stands; the list was
-- simply short.
--
-- **This guard still only reads names.** A token stored under a clean key —
-- `general.timezone` holding an access key — is accepted, and no pattern over
-- names can catch it. The review recorded that as its own finding rather than
-- being folded in here, because a value-shaped check is a different decision
-- with different false positives, and this migration should not imply one was
-- made.

create or replace function public.setting_holds_no_secret(p_key text, p_value jsonb)
returns boolean as $$
  select
    p_key !~* '(secret|token|password|passwd|credential|signing|encryption|(private|access|api|secret|ssh|signing|encryption)_?key)'
    and not coalesce(
      jsonb_path_exists(
        p_value,
        '$.**.keyvalue() ? (@.key like_regex "(secret|token|password|passwd|credential|signing|encryption|(private|access|api|secret|ssh|signing|encryption)_?key)" flag "i")',
        '{}'::jsonb,
        -- Suppress the error a scalar raises, and read the NULL it then
        -- returns as "found nothing" rather than as "constraint satisfied".
        true
      ),
      false
    );
$$ language sql immutable;

-- The three constraints reference the function by name and are re-checked on
-- write, not on replace -- so rows already stored under the old guard are not
-- re-examined. That is deliberate and worth stating: this closes the door, and
-- an estate that has been running with it open needs a separate look at what
-- came through. On 2026-09-19 the answer is none, because no product declares
-- an OBJECT setting yet.
