-- Migration: 00016_report_schedule_locale
-- The language a scheduled report's delivery is written in.
--
-- A schedule is created by one person and read by up to ten others, at six
-- in the morning with nobody signed in, so the worker cannot ask anybody
-- which language to write the covering mail in. The person creating the
-- schedule names it (or the API records the language they were using), and
-- the worker reads it back here. Two letters, checked against the languages
-- the mail catalogue speaks; the API validates against the same list before
-- writing. Existing rows are English, which is what they were delivered in.

alter table public.report_schedules
  add column locale text not null default 'en'
    check (locale in ('en', 'de', 'es'));
