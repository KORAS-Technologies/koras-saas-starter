'use client'

import { useEffect, useState } from 'react'
import { formatWhen } from './run-stage'

/**
 * A stored UTC instant, shown on the reader's own clock.
 *
 * The first render -- the server's, and the browser's before it has mounted --
 * is in UTC and says so, so the two agree and hydration is exact; once mounted
 * it switches to the browser's own zone. The machine-readable value stays on
 * the element, and nothing stored or sent changes.
 */
export function LocalTime({ iso, locale }: { iso: string; locale: string }) {
  const [text, setText] = useState(() => formatWhen(iso, locale, 'UTC'))
  useEffect(() => {
    setText(formatWhen(iso, locale))
  }, [iso, locale])
  return (
    <time dateTime={iso} title={iso} suppressHydrationWarning>
      {text}
    </time>
  )
}
