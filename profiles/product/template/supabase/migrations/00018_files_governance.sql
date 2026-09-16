-- Migration: 00018_files_governance
-- What is true about a stored object besides its name: integrity, where it sits
-- in its life, and whether anything forbids removing it.
--
-- The index this extends has recorded a name, a size and two states since
-- 00005. That is enough to list files and not enough to govern them: nothing
-- recorded a digest, so no copy of an object could be compared with the
-- original; nothing recorded a retention date, so deletion was whenever
-- somebody clicked; and nothing recorded a hold, so a purge could not be
-- stopped. Every column below exists because a question could not be answered
-- without it.
--
-- Columns rather than a second table. An object table beside this one would
-- describe the same objects twice and have to be kept in agreement, and the
-- agreement is the part that fails.
--
-- No `deleted_at`. This schema has carried no soft-delete column since it was
-- written, and deletion here is a state plus a date, which answers the same
-- question with one idiom instead of two.

alter table public.files
  -- The organization the tenant belonged to when the object was stored.
  -- Denormalized on purpose: it is a mutable fact, so it is recorded here and
  -- never put in the object key, where a tenant changing organization would
  -- mean copying every object it owns.
  add column if not exists organization_id text,

  -- documents, exports, imports, attachments, generated, reports, archives,
  -- temp. The segment the object key carries from 00018 onward; the rows
  -- written before it have their category recorded and their old key kept,
  -- because rewriting a key would break every row that stores one.
  add column if not exists category text not null default 'documents',

  -- The digest, and whether anyone but the client vouched for it. A browser
  -- asserting a digest is evidence; a provider echoing one is proof. Two
  -- columns, so no reader has to guess which of the two they are holding --
  -- a single column would make a claim look like a measurement.
  add column if not exists checksum_sha256 text,
  add column if not exists checksum_verified_at timestamptz,

  -- How sensitive the object is, and which retention rule applies to it.
  -- Both are names resolved in code: the platform's floor, a product policy
  -- and a tenant's own are reconciled there, not here, because precedence is
  -- a rule and not a column.
  add column if not exists classification text not null default 'standard',
  add column if not exists retention_policy text,

  -- When retention stops protecting the object. Null means no policy has been
  -- resolved for it, which is not the same as expired, and the sweep must
  -- treat it as not-yet-eligible rather than as due.
  add column if not exists retain_until timestamptz,

  -- A hold outranks retention: while this is true the object is not archived,
  -- not purged and not removed by any sweep, whatever its dates say.
  add column if not exists legal_hold boolean not null default false,

  -- pending, clean, infected, skipped. No scanner is wired to this; the
  -- column and the `quarantined` state exist so that adding one is a change
  -- of code rather than a change of schema.
  add column if not exists scan_status text not null default 'pending',
  add column if not exists scan_note text,

  -- When the object was copied to the archive destination. Cold is metadata
  -- and archive is a copy: no provider this estate uses offers tiers, so the
  -- lifecycle is Koras's and this is the only physical move in it.
  add column if not exists archived_at timestamptz,

  -- Whether a verified copy exists, and when it was last verified. `copied`
  -- is what a provider's success means; `verified` is what a matching digest
  -- means, and only the second is a backup.
  add column if not exists backup_status text not null default 'none',
  add column if not exists backed_up_at timestamptz,

  -- What the object is attached to, where a product attaches files to its own
  -- records. Both null for a file that is simply a file.
  add column if not exists entity_type text,
  add column if not exists entity_id text,

  -- Reserved, and inert. The starter has no workspace below a tenant and no
  -- object versioning; both are modelled here so that adding either later is
  -- not a migration against every row, and neither is read by anything today
  -- (2026-09-15). `version` is 1 for every object until something writes a 2.
  add column if not exists workspace_id uuid,
  add column if not exists version integer not null default 1;

-- The vocabularies, as text with a check rather than an enum, the way every
-- other state column in this schema is written.
alter table public.files drop constraint if exists files_status_check;
alter table public.files add constraint files_status_check
  check (status in ('pending', 'ready', 'quarantined', 'archived', 'deleted', 'purged'));

alter table public.files drop constraint if exists files_category_check;
alter table public.files add constraint files_category_check
  check (category in ('documents', 'exports', 'imports', 'attachments',
                      'generated', 'reports', 'archives', 'temp'));

alter table public.files drop constraint if exists files_classification_check;
alter table public.files add constraint files_classification_check
  check (classification in ('standard', 'sensitive', 'restricted'));

alter table public.files drop constraint if exists files_scan_status_check;
alter table public.files add constraint files_scan_status_check
  check (scan_status in ('pending', 'clean', 'infected', 'skipped'));

alter table public.files drop constraint if exists files_backup_status_check;
alter table public.files add constraint files_backup_status_check
  check (backup_status in ('none', 'copied', 'verified', 'failed'));

alter table public.files drop constraint if exists files_version_check;
alter table public.files add constraint files_version_check check (version >= 1);

-- No new index. The queries these columns will serve -- the retention sweep,
-- the reconciliation listing, the backup selection -- do not exist yet
-- (2026-09-15), and an index named for a query nobody has written is an index
-- nobody can justify keeping. Each arrives with the sweep that needs it.
