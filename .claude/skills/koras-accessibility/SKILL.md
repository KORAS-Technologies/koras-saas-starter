---
name: koras-accessibility
description: Koras Accessibility guidance for Koras applications.
---

# Koras Accessibility

Use this skill for user-facing UI changes. Target WCAG 2.2 AA.

## Semantic Structure

- Use native semantic elements before ARIA recreation.
- Maintain logical heading order.
- Use landmarks where appropriate.
- Give interactive controls accessible names.

## Keyboard

Every interactive function must be operable with keyboard alone. Verify logical Tab order, visible focus, Escape behavior for dismissible overlays, and focus return after dialogs close.

## Forms

- programmatic labels
- required state conveyed accessibly
- `aria-invalid` for invalid fields
- associate help/error text with `aria-describedby`
- provide useful error text, not color alone
- move or guide focus to errors after failed submit when appropriate

## Visual

- do not rely on color alone
- preserve text resizing/zoom usability
- use adequate touch target sizes
- avoid clipped content at responsive breakpoints
- ensure focus indicators are visible against the background

## Motion

Respect reduced-motion preferences for non-essential animation.

## Images and Icons

- informative images need useful alternative text
- decorative images/icons should not create screen-reader noise
- icon-only controls need accessible labels/tooltips where appropriate

## Dynamic Content

Use appropriate live-region/status semantics for meaningful async changes such as form submission results, background processing, or validation summaries when users would otherwise miss the update.

## Testing

At minimum for changed flows:

1. keyboard-only pass
2. focus visibility check
3. labels/errors check
4. mobile/reflow check
5. automated accessibility tooling when present

Automated checks do not replace manual keyboard/semantic review.
