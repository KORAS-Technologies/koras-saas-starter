'use client'

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { ReactNode } from 'react'
import { cn } from '../lib/cn'

/**
 * Immediate feedback for something the person just did.
 *
 * A toast is not a notification. The division this design system draws:
 *
 * - a **toast** confirms an action, to the person who took it, now. It goes
 *   away, because the thing it describes is over.
 * - a **banner** states a condition that is still true, so it stays.
 * - a **notification** is something a person needs to know or act on, which
 *   outlives the page they were on, so it is a row in a table and a line in
 *   the bell.
 *
 * **Deliberately not a library.** A toast is a list, a timer and a live
 * region; the smallest popular package is tens of kilobytes shipped to every
 * generated product for that. What a library would buy — stacking, swipe,
 * promise helpers — is not asked for by anything here.
 *
 * **One live region, not one per toast.** A region per toast makes a screen
 * reader announce the region rather than the message, and announces nothing at
 * all when the region appears at the same moment as its content. So the region
 * is always in the document and only its children change.
 *
 * `polite`, not `assertive`: a toast confirms something the person just did,
 * and interrupting them to say their own action worked is rude. Something that
 * must interrupt is an error, and an error belongs in a `Banner` beside the
 * control that produced it.
 */

export type ToastTone = 'info' | 'success' | 'warning' | 'error'

export type Toast = {
  id: string
  tone: ToastTone
  message: string
}

type ToastContext = {
  toasts: readonly Toast[]
  show: (message: string, tone?: ToastTone) => void
  dismiss: (id: string) => void
}

const Toasts = createContext<ToastContext | null>(null)

/** Milliseconds a toast stays. Four seconds reads comfortably twice. */
export const TOAST_MS = 4000

/** More than this on screen at once and the oldest goes: a column of eleven is a wall. */
export const MAX_TOASTS = 3

export function ToastProvider({
  children,
  autoDismissMs = TOAST_MS,
}: {
  children: ReactNode
  /** Zero keeps every toast until it is dismissed. Tests use it. */
  autoDismissMs?: number
}) {
  const [toasts, setToasts] = useState<readonly Toast[]>([])
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>())

  const dismiss = useCallback((id: string) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
    const timer = timers.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.current.delete(id)
    }
  }, [])

  const show = useCallback(
    (message: string, tone: ToastTone = 'info') => {
      const id = `${String(Date.now())}-${String(Math.random()).slice(2, 8)}`
      setToasts((current) => [...current, { id, tone, message }].slice(-MAX_TOASTS))
      if (autoDismissMs > 0) {
        timers.current.set(
          id,
          setTimeout(() => {
            dismiss(id)
          }, autoDismissMs),
        )
      }
    },
    [autoDismissMs, dismiss],
  )

  // Every pending timer, on unmount. A timer holding a closure over a setter
  // for an unmounted tree is the warning nobody reads and the leak nobody
  // measures.
  const held = timers.current
  useEffect(
    () => () => {
      for (const timer of held.values()) clearTimeout(timer)
      held.clear()
    },
    [held],
  )

  const value = useMemo(() => ({ toasts, show, dismiss }), [toasts, show, dismiss])

  return (
    <Toasts.Provider value={value}>
      {children}
      <ToastRegion toasts={toasts} onDismiss={dismiss} />
    </Toasts.Provider>
  )
}

/**
 * Raise a toast from anywhere inside the provider.
 *
 * Outside one it returns a no-op rather than throwing. A component that
 * renders in two places — a page with the shell and a page without — should
 * not crash the one without because it tried to confirm something.
 */
export function useToast(): ToastContext {
  return (
    useContext(Toasts) ?? {
      toasts: [],
      show: () => undefined,
      dismiss: () => undefined,
    }
  )
}

function ToastRegion({
  toasts,
  onDismiss,
}: {
  toasts: readonly Toast[]
  onDismiss: (id: string) => void
}) {
  return (
    <div
      // Always present, so the announcement is the message rather than the
      // region appearing.
      role="status"
      aria-live="polite"
      aria-atomic="false"
      data-testid="toast-region"
      className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-center gap-2 p-4 sm:inset-x-auto sm:right-0"
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          data-testid="toast"
          data-tone={toast.tone}
          className={cn(
            'pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-brand border p-3 text-sm shadow-card',
            // No entrance animation. One that respects `prefers-reduced-motion`
            // is four more lines and one that does not is a vestibular
            // trigger; a toast that simply appears is neither.
            TONES[toast.tone],
          )}
        >
          <span className="min-w-0 flex-1 text-ink">{toast.message}</span>
          <button
            type="button"
            onClick={() => {
              onDismiss(toast.id)
            }}
            className="-my-1 -mr-1 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-brand text-ink-muted hover:bg-surface-muted"
          >
            <span className="sr-only">Dismiss</span>
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              className="h-4 w-4"
              aria-hidden="true"
              focusable="false"
            >
              <path d="m6 6 12 12M18 6 6 18" />
            </svg>
          </button>
        </div>
      ))}
    </div>
  )
}

const TONES: Record<ToastTone, string> = {
  info: 'border-line bg-surface',
  success: 'border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950',
  warning: 'border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950',
  error: 'border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950',
}
