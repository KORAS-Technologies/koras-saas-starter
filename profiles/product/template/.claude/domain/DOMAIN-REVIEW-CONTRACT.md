# Domain Review Contract

What a domain review must establish before the domain gate can close. This
contract ships with the starter; the agent that performs the review is
product-created.

## When the gate applies

Only when the product has a `domain-registry.yaml` and the feature matches one
of its `domain_review.required_for` triggers. A product with no domain layer
has no domain gate, and that is a valid configuration rather than a gap.

## What the review must establish

1. **Rule conformance.** Every domain rule the feature touches is implemented
   as stated, with its exceptions.
2. **Vocabulary.** Domain terms in the UI, API, schema and documentation mean
   what the domain says they mean, and the same thing in each place.
3. **Lifecycle correctness.** State transitions the feature introduces are
   legal ones, and illegal transitions are actually prevented rather than
   merely undocumented.
4. **Calculation correctness.** Any figure the feature computes is checked
   against the authoritative definition, on at least one worked example.
5. **Missing cases.** Domain cases the requirements omitted are named, with
   whether each is in scope or deferred.
6. **Sources cited.** Every finding names the document or system that makes it
   a rule. A finding with no source is an opinion.

## What the review may not do

- It may not approve a feature the reviewer specified the requirements for,
  where the product has another domain agent available.
- It may not substitute for the engineering gates. Domain-correct and insecure,
  inaccessible or untested is not done.
- It may not resolve an ambiguous rule by choosing one reading; ambiguity is
  escalated to a human.

## Output

- Per-rule verdicts with sources.
- Findings classified CRITICAL, HIGH, MEDIUM or LOW.
- An explicit gate verdict: domain review passed, or blocked with reasons.

CRITICAL and HIGH domain findings block completion until fixed and
independently revalidated, exactly like any other blocking finding.
