# Feature Documentation Templates

Templates for the canonical feature documentation structure. The authoritative
definition of that structure — which files are required, when, and where — is
`.claude/orchestration/documentation-policy.yaml`. If a template and the policy
disagree, the policy wins and the template is the defect.

Copy into:

```text
docs/features/<feature-id>-<slug>/
  requirements/   user-story.md
  design/         technical-design.md, functional-design.md, ux-design.md
  testing/        test-plan.md, automated-test-results.md, regression-results.md
                  manual/manual-test-guide.md, manual/manual-test-results.md
                  manual/screenshots/<test-case-id>/step-<nn>-<description>.png
  security/       threat-model.md, security-review.md
  documentation/  user-guide.md, admin-guide.md
  release/        release-notes.md
```

Replace every placeholder. A template placeholder left in a delivered document
is a documentation defect, and `qa-reviewer` reports it as one.
