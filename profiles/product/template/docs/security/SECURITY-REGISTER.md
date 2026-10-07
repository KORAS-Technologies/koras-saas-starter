# Security register

The promotion gate (`python -m promotion gate`) reads this table and fails while any finding of
type `SECURITY` or `SECURITY-GAP` with severity Critical or High is unresolved. It is parsed
strictly: the header row names the columns, a row it cannot parse FAILS the gate, and a register
with a header and no rows fails unless it carries the explicit marker below. Which ids the first
cell may take is `register.id_pattern` in `local/config/promotion.yaml`.

A finding is resolved only when its Status holds `RESOLVED`, `CLOSED`, `WITHDRAWN` or
`SUPERSEDED` as a whole upper-case word, not preceded by NOT, UN, PARTIALLY, TO BE, UNTIL or
BLOCKED. A later row for the same id supersedes an earlier one.

| ID | Type | Severity | Status | Title |
|---|---|---|---|---|

<!-- koras:register-empty -->
