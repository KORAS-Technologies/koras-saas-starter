# <FEATURE-ID> — Threat Model

## Assets

| Asset | Sensitivity | Owner |
|-------|-------------|-------|

## Actors

| Actor | Trusted? | Capabilities |
|-------|----------|--------------|

## Entry points

| Entry point | Reachable by | Authentication | Authorization |
|-------------|--------------|----------------|---------------|

## Trust boundaries

| Boundary | Crossed by | Must be verified |
|----------|-----------|------------------|

## Authorization matrix

| Principal | Permission | Tenant scope | Enforced at |
|-----------|-----------|--------------|-------------|

## Required controls

| # | Control | Enforcement point | Verified by |
|---|---------|-------------------|-------------|

## Abuse cases

Handed to `security-test` as executable expectations.

| # | Abuse case | Expected outcome |
|---|-----------|------------------|
| AB-1 | Principal of tenant B attempts to read tenant A's record | Refused; existence not disclosed |
| AB-2 | Principal without the permission attempts the operation | Refused |
| AB-3 | <injection appropriate to the surface> | <rejected> |

## Secrets

<Which credentials are involved, where they live, and confirmation that none can reach a client bundle or browser-reachable path.>
