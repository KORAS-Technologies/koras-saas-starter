'use client'

import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { cn } from '../lib/cn'

/**
 * Light, dark, or whatever the machine says.
 *
 * Three states rather than two, and the third is the default. A two-state
 * toggle has to guess on first load, and it guesses wrong for everybody whose
 * operating system is already set the other way -- so "System" is a real
 * position here, not an absence.
 *
 * **The switch is `color-scheme` on <html>, and nothing else.** Every colour in
 * the product resolves through `light-dark()` pairs declared by `brandStyle`,
 * so setting that one property re-paints the whole application -- including a
 * customer's own tokens under `BrandScope`, because each of those is a pair
 * too. There is no class to add, no palette to swap, and no component that
 * knows an appearance exists.
 *
 * It also fixes what the product does not draw: form controls, scrollbars and
 * the canvas behind an overscroll all follow `color-scheme`, and those are
 * exactly the things that stay white in a hand-rolled dark mode.
 *
 * The choice is stored in `localStorage` and applied before paint by a small
 * script in the root layout. Without that script a reader who chose dark sees
 * a light flash on every navigation to a fresh document -- which is the one
 * bug every dark mode ships with.
 */
export const THEME_STORAGE_KEY = 'koras-theme'

export type ThemeChoice = 'light' | 'dark' | 'system'

/**
 * The script that runs before the first paint.
 *
 * Exported as a string so the layout can put it in a `<script>` with the
 * request nonce. It is deliberately tiny and dependency-free: it runs before
 * React, before hydration, and before anything is on screen.
 *
 * Wrapped in try/catch because `localStorage` throws outright in some privacy
 * modes rather than returning null, and an exception here would leave the
 * document unstyled.
 */
export const THEME_SCRIPT = `try{var t=localStorage.getItem('${THEME_STORAGE_KEY}');if(t==='light'||t==='dark')document.documentElement.style.colorScheme=t}catch(e){}`

function apply(choice: ThemeChoice): void {
  // 'system' clears the override rather than writing a value, so the document
  // goes back to the `color-scheme: light dark` in the stylesheet and follows
  // the operating system again.
  document.documentElement.style.colorScheme = choice === 'system' ? '' : choice
  try {
    if (choice === 'system') localStorage.removeItem(THEME_STORAGE_KEY)
    else localStorage.setItem(THEME_STORAGE_KEY, choice)
  } catch {
    // Private browsing, a blocked origin, a quota. The appearance still
    // changes for this page; it simply does not survive the next one.
  }
}

const CHOICES: { value: ThemeChoice; label: string; glyph: ReactNode }[] = [
  {
    value: 'light',
    label: 'Light',
    glyph: (
      <g>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </g>
    ),
  },
  {
    value: 'system',
    label: 'System',
    glyph: (
      <g>
        <rect x="3" y="4" width="18" height="12" rx="2" />
        <path d="M8 20h8" />
      </g>
    ),
  },
  {
    value: 'dark',
    label: 'Dark',
    glyph: <path d="M20 14.5A8 8 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z" />,
  },
]

export function ThemeToggle({ className }: { className?: string }) {
  // Starts as `system` on the server and on the first client render, because
  // that is what the markup says and disagreeing with it is a hydration error.
  // The stored choice is read in an effect and shown a frame later; the *page*
  // is already correct by then, painted by THEME_SCRIPT.
  const [choice, setChoice] = useState<ThemeChoice>('system')

  useEffect(() => {
    try {
      const stored = localStorage.getItem(THEME_STORAGE_KEY)
      if (stored === 'light' || stored === 'dark') setChoice(stored)
    } catch {
      // As above: the control shows System and the page is unaffected.
    }
  }, [])

  return (
    // A radio group, not three buttons. Three of the same control where exactly
    // one is chosen is what a radio group is, and it gets arrow-key navigation
    // and a single tab stop from the browser rather than from us.
    <div
      role="radiogroup"
      aria-label="Appearance"
      className={cn(
        'inline-flex items-center gap-0.5 rounded-brand border border-line p-0.5',
        className,
      )}
    >
      {CHOICES.map((option) => {
        const selected = option.value === choice
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => {
              setChoice(option.value)
              apply(option.value)
            }}
            className={cn(
              'inline-flex h-9 w-9 items-center justify-center rounded-brand transition-colors',
              selected
                ? 'bg-brand/10 text-brand'
                : 'text-ink-muted hover:bg-surface-muted hover:text-ink',
            )}
          >
            <span className="sr-only">{option.label}</span>
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
              className="h-4 w-4"
            >
              {option.glyph}
            </svg>
          </button>
        )
      })}
    </div>
  )
}
