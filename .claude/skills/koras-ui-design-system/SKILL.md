---
name: koras-ui-design-system
description: Koras UI Design System guidance for Koras applications.
---

# Koras UI Design System

Use this skill when creating or changing product UI.

## Primary Rule

Search existing shared UI before creating a new primitive.

## Component Order

Prefer:

```text
existing project component
-> existing packages/ui component
-> existing shadcn/Radix primitive
-> composed reusable component
-> new primitive only when genuinely required
```

## Design Rules

- Use semantic design tokens and established CSS variables.
- Avoid hardcoded product colors when a token exists.
- Do not introduce a second spacing, typography, radius, shadow, or icon system.
- Keep visual hierarchy intentional and consistent.
- Use composition instead of large components controlled by many boolean props.
- Keep variants explicit and small.
- Avoid arbitrary z-index values; use the project layering convention.

## Responsive Requirements

User-facing UI should be usable on desktop, tablet, and mobile. Do not simply hide core actions on small screens. Reflow, collapse, stack, or provide an equivalent interaction.

## Required States

Reusable components should account for applicable:

- default
- hover
- focus-visible
- active
- disabled
- loading
- error
- empty
- selected

## Forms

Fields must have accessible labels and error relationships. Use shared field wrappers/components where available.

## Tables and Dense Data

For data tables consider:

- loading
- empty state
- pagination or virtualization when needed
- responsive behavior
- accessible action menus
- sortable/filterable state clarity
- row selection semantics

## Dialogs and Overlays

Use established dialog/sheet/popover primitives. Preserve focus trapping, Escape behavior, focus return, and accessible names.

## Avoid

- page-local duplicate buttons/dialogs/toasts
- nested clickable controls
- icons without accessible names when meaning is not obvious
- color-only status communication
- fake buttons implemented as non-interactive elements
