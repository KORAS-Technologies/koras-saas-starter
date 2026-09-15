# <FEATURE-ID> — Security Review

**Reviewed by:** <agent — must not be the agent that implemented or specified the change>
**Build / commit:** <sha>
**Review date:** <YYYY-MM-DD>

## Control verification

| # | Control | Specified at | Implemented at | Verified | Verdict |
|---|---------|--------------|----------------|----------|---------|

A control that was not exercised is not verified.

## Abuse case results

| # | Abuse case | Executed | Outcome |
|---|-----------|----------|---------|

## Findings

| # | Finding | Severity | Location | Exploitation impact | Fix |
|---|---------|----------|----------|--------------------|-----|

Severity is CRITICAL, HIGH, MEDIUM or LOW. CRITICAL and HIGH block the gate.

## Checklist

- [ ] Tenancy resolved from trusted context on every changed path
- [ ] No secret reachable from a client bundle or browser-reachable route
- [ ] Input validated server-side; injection defences at the relevant surfaces
- [ ] Webhooks verified; redirects allow-listed; SSRF constrained
- [ ] Audit events carry tenant context and no secrets or personal data
- [ ] Rate limiting engages where the surface invites abuse
- [ ] No control disabled or weakened to make the feature work

## Verdict

<Clear of CRITICAL and HIGH, or blocked with the findings above.>
