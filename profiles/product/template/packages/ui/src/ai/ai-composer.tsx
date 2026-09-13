'use client'

import { useId, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { Button } from '../primitives/button'

/**
 * Where a person types.
 *
 * A form with a labelled textarea and a submit: Enter sends, Shift+Enter
 * makes a new line, and both are announced by the label's hint. While a turn
 * is running the control is disabled and the button says so -- a second
 * submission is refused by the button the way every form here refuses one,
 * and the reason reaches a screen reader through `aria-busy`.
 */
export function AIComposer({
  label,
  placeholder,
  sendLabel,
  sendingLabel,
  busy,
  disabled = false,
  maxLength = 8000,
  onSend,
}: {
  label: string
  placeholder: string
  sendLabel: string
  sendingLabel: string
  busy: boolean
  disabled?: boolean
  maxLength?: number
  onSend: (text: string) => void
}) {
  const [text, setText] = useState('')
  const id = useId()
  const canSend = text.trim().length > 0 && !busy && !disabled

  const submit = () => {
    if (!canSend) return
    onSend(text.trim())
    setText('')
  }

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    submit()
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="flex items-end gap-2 border-t border-line bg-surface px-4 py-3"
      data-testid="assistant-composer"
    >
      <div className="flex-1">
        <label htmlFor={id} className="sr-only">
          {label}
        </label>
        <textarea
          id={id}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          rows={2}
          maxLength={maxLength}
          disabled={busy || disabled}
          aria-busy={busy || undefined}
          className="w-full resize-none rounded-brand border border-line bg-surface px-3.5 py-2.5 text-base text-ink placeholder:text-ink-muted/70 disabled:opacity-60"
        />
      </div>
      <Button type="submit" loading={busy} disabled={!canSend} data-testid="assistant-send">
        {busy ? sendingLabel : sendLabel}
      </Button>
    </form>
  )
}
