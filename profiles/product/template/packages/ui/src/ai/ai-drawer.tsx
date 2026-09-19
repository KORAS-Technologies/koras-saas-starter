'use client'

import type { ReactNode, RefObject } from 'react'

import { Drawer } from '../primitives/drawer'

/**
 * The panel the assistant lives in, over the page and to its right.
 *
 * A dialog, and treated as one: focus goes in when it opens, Tab wraps at the
 * ends, Escape closes it, and focus goes back to the control that opened it.
 *
 * **All of that now lives in `Drawer`.** It was hand-written here, with a note
 * saying a second copy of the focus trap was cheaper than a library shipped to
 * every product for two panels. That was true at two. The notification drawer
 * made three on 2026-09-19, so the trap moved to a primitive and this became
 * the assistant's two differences from it: where focus lands, and what the
 * browser tests look for.
 */
export function AIDrawer({
  id,
  open,
  title,
  closeLabel,
  onClose,
  returnFocusTo,
  children,
}: {
  id: string
  open: boolean
  title: string
  closeLabel: string
  onClose: () => void
  /** The trigger, so closing hands the focus back. */
  returnFocusTo?: RefObject<HTMLButtonElement | null>
  children: ReactNode
}) {
  return (
    <Drawer
      id={id}
      open={open}
      title={title}
      closeLabel={closeLabel}
      onClose={onClose}
      returnFocusTo={returnFocusTo}
      // The composer, where a person opening an assistant expects to type.
      initialFocusSelector="textarea"
      testId="assistant-drawer"
    >
      {children}
    </Drawer>
  )
}
