import { describe, it, expect, vi } from 'vitest'

/**
 * The shared field's accessibility contract, executed rather than read.
 *
 * `field.tsx` is a pure function of its props, so it is imported out of the
 * template and walked as an element tree. React is not a dependency of this
 * package and is not added for this: `React.createElement` is a
 * three-line element factory, and function components are expanded by calling
 * them. What this proves is the markup the component describes, in DOM order.
 * It does not prove how a browser or a screen reader presents that markup.
 */
vi.hoisted(() => {
  // The vitest config transforms with an empty tsconfig, so JSX compiles to the
  // classic `React.createElement`. A global of that name is all it needs.
  const createElement = (
    type: unknown,
    props: Record<string, unknown> | null,
    ...kids: unknown[]
  ) => ({
    type,
    props: {
      ...(props ?? {}),
      ...(kids.length > 0 ? { children: kids.length === 1 ? kids[0] : kids } : {}),
    },
  })
  ;(globalThis as Record<string, unknown>).React = { createElement }
})

import {
  SelectField,
  TextField,
} from '../../../profiles/product/template/packages/ui/src/primitives/field'

interface Node {
  tag: string
  props: Record<string, unknown>
  text: string
}

/** Expand components and flatten the tree to elements in document order. */
function walk(el: unknown, out: Node[] = []): Node[] {
  if (el === null || el === undefined || el === false || el === true) return out
  if (typeof el === 'string' || typeof el === 'number') return out
  if (Array.isArray(el)) {
    el.forEach((child) => walk(child, out))
    return out
  }
  const { type, props } = el as { type: unknown; props: Record<string, unknown> }
  if (typeof type === 'function') return walk((type as (p: unknown) => unknown)(props), out)
  out.push({ tag: String(type), props, text: textOf(props.children) })
  walk(props.children, out)
  return out
}

function textOf(children: unknown): string {
  if (typeof children === 'string' || typeof children === 'number') return String(children)
  if (Array.isArray(children)) return children.map(textOf).join('')
  return ''
}

const FOCUSABLE = new Set(['input', 'select', 'textarea', 'button'])

function select(extra: Record<string, unknown> = {}) {
  return walk(
    SelectField({
      id: 'f',
      label: 'Existing records',
      hint: 'What to do with rows that already exist',
      children: [],
      ...extra,
    } as never),
  )
}

const control = (nodes: Node[]) => nodes.find((n) => n.tag === 'select' || n.tag === 'input')!
const byId = (nodes: Node[], id: string) => nodes.filter((n) => n.props.id === id)
const order = (nodes: Node[]) => nodes.map((n) => n.props.id ?? n.tag)

describe.each([
  ['above (default)', {}],
  ['above (explicit)', { hintPlacement: 'above' }],
  ['below', { hintPlacement: 'below' }],
])('field with hint, placement %s', (_name, extra) => {
  it('names the control from its label and the label targets the control id', () => {
    const nodes = select(extra)
    const label = nodes.find((n) => n.tag === 'label')!
    expect(label.props.htmlFor).toBe('f')
    expect(label.text).toBe('Existing records')
    expect(control(nodes).props.id).toBe('f')
  })

  it('describes the control by a hint element that exists exactly once', () => {
    const nodes = select(extra)
    expect(control(nodes).props['aria-describedby']).toBe('f-hint')
    const hint = byId(nodes, 'f-hint')
    expect(hint).toHaveLength(1)
    expect(hint[0].text).toBe('What to do with rows that already exist')
  })

  it('adds the error to the description, marks the control invalid and announces the error', () => {
    const nodes = select({ ...extra, error: 'Choose one' })
    expect(control(nodes).props['aria-describedby']).toBe('f-hint f-error')
    expect(control(nodes).props['aria-invalid']).toBe(true)
    const err = byId(nodes, 'f-error')
    expect(err).toHaveLength(1)
    expect(err[0].props.role).toBe('alert')
    expect(err[0].text).toBe('Choose one')
  })

  it('has no aria-invalid and no error element when valid', () => {
    const nodes = select(extra)
    expect(control(nodes).props['aria-invalid']).toBeUndefined()
    expect(byId(nodes, 'f-error')).toHaveLength(0)
  })

  it('has one tab stop: the control; the hint and label are not focusable', () => {
    const nodes = select({ ...extra, error: 'Choose one' })
    const stops = nodes.filter(
      (n) =>
        FOCUSABLE.has(n.tag) || (typeof n.props.tabIndex === 'number' && n.props.tabIndex >= 0),
    )
    expect(stops.map((n) => n.props.id)).toEqual(['f'])
    for (const n of nodes.filter((x) => x.tag === 'p' || x.tag === 'label')) {
      expect(n.props.tabIndex).toBeUndefined()
      expect(n.props.role === undefined || n.props.role === 'alert').toBe(true)
    }
  })
})

describe('DOM order, which is also the reading order and the focus order', () => {
  it('default keeps label, hint, control', () => {
    expect(order(select())).toEqual(['div', 'label', 'f-hint', 'div', 'f'].filter(Boolean))
  })

  it('below is label, control, hint, and the error follows the hint', () => {
    expect(order(select({ hintPlacement: 'below', error: 'x' }))).toEqual([
      'div',
      'label',
      'div',
      'f',
      'f-hint',
      'f-error',
    ])
  })
})

describe('a consumer that does not pass hintPlacement keeps the long-standing markup', () => {
  it('SelectField without the prop is identical to hintPlacement="above"', () => {
    expect(select()).toEqual(select({ hintPlacement: 'above' }))
  })

  it('TextField (which has no placement prop) keeps label, hint, control, error', () => {
    const nodes = walk(TextField({ id: 't', label: 'Name', hint: 'h', error: 'e' } as never))
    expect(order(nodes)).toEqual(['div', 'label', 't-hint', 'div', 't', 't-error'])
    expect(control(nodes).props['aria-describedby']).toBe('t-hint t-error')
    const hint = byId(nodes, 't-hint')[0]
    expect(hint.props.className).toBe('mt-1 text-sm text-ink-muted')
  })

  it('draws no hint element and no aria-describedby when there is no hint', () => {
    const nodes = walk(
      SelectField({ id: 's', label: 'L', children: [], hintPlacement: 'below' } as never),
    )
    expect(byId(nodes, 's-hint')).toHaveLength(0)
    expect(control(nodes).props['aria-describedby']).toBeUndefined()
  })
})
