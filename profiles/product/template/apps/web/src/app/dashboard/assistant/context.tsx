'use client'

import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

/**
 * Which screen the assistant was opened beside.
 *
 * A page that wants the assistant to know what it shows renders
 * `<AIPageScope type="document" id={document.id} />` anywhere inside the
 * signed-in area; the launcher reads it and sends it with the conversation.
 * The starter names no resource type of its own -- the product's entities
 * are the product's -- so this carries two strings and no opinion about them.
 *
 * Informational, on purpose. The API records it beside the conversation and
 * the prompt mentions it; it scopes nothing and authorises nothing, and a tool
 * that reads the resource it names still runs under the tenant session and
 * checks its own permission. A value a browser sent is a request, not
 * evidence, and this is a value a browser sent.
 */
export interface AIPageRef {
  type: string
  id: string
}

interface AIPageContextValue {
  page: AIPageRef | null
  setPage: (page: AIPageRef | null) => void
}

const AIPageContext = createContext<AIPageContextValue>({ page: null, setPage: () => {} })

export function AIPageContextProvider({ children }: { children: ReactNode }) {
  const [page, setPage] = useState<AIPageRef | null>(null)
  const value = useMemo(() => ({ page, setPage }), [page])
  return <AIPageContext.Provider value={value}>{children}</AIPageContext.Provider>
}

export function useAIPageContext(): AIPageRef | null {
  return useContext(AIPageContext).page
}

/** Declares the resource a page shows, for as long as the page is mounted. */
export function AIPageScope({ type, id }: { type: string; id: string }) {
  const { setPage } = useContext(AIPageContext)
  useEffect(() => {
    setPage({ type, id })
    return () => setPage(null)
  }, [type, id, setPage])
  return null
}
