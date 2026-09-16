-- Migration: 00019_audit_classification
-- What kind of record each audit row is, so that one sweep can keep them for
-- different lengths of time.
--
-- Retention was one number for the whole table: a year for everything, which
-- is too long for "somebody opened a file" and too short for "somebody was
-- refused access to one". Both were swept on the same night by the same
-- delete, because nothing on the row said which was which.
--
-- Four classes, and the class belongs to the action rather than to the caller:
-- `koras_audit` carries a registry of the actions this build can record, each
-- declared with its class, and an action nobody declared is refused at the
-- point of recording. A caller choosing the class per call is how a security
-- event ends up swept with the activity.
--
-- The column is written by the sink from that registry, never by a request.
-- Nothing a browser sends reaches it.

alter table public.audit_events
  add column if not exists classification text not null default 'audit';

alter table public.audit_events drop constraint if exists audit_events_classification_check;
alter table public.audit_events add constraint audit_events_classification_check
  check (classification in ('activity', 'audit', 'security', 'administrative'));

-- The sweep deletes by class and age together, and this is the index that
-- makes that one range scan per class rather than a scan of the table:
--   delete from audit_events where classification = :class and created_at < :before
create index if not exists audit_events_class_time_idx
  on public.audit_events (classification, created_at);

-- Rows written before this migration keep the default, `audit`, which is the
-- class the single retention number already meant. Nothing is reclassified
-- retrospectively: a row's class is what was true when it was recorded.
